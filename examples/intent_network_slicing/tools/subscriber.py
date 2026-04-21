"""Structured subscriber mutation tools for intent-oriented tasks."""

from __future__ import annotations

import json

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

from action_journal import record_action


def _normalize_imsi(imsi: str) -> str:
    """Normalize IMSI input to a 15-digit string."""
    value = str(imsi).strip()
    if value.startswith("imsi-"):
        value = value[5:]
    if not value.isdigit() or len(value) != 15:
        raise ToolError("IMSI must be a 15-digit numeric string")
    return value


def _normalize_sst(sst: int | str) -> int:
    """Validate SST range."""
    try:
        value = int(sst)
    except (TypeError, ValueError) as exc:
        raise ToolError("SST must be an integer") from exc
    if value < 0 or value > 255:
        raise ToolError("SST must be between 0 and 255")
    return value


def _normalize_sd(sd: str | int) -> str:
    """Normalize SD to a six-character lowercase hex string."""
    if isinstance(sd, int):
        if sd < 0 or sd > 0xFFFFFF:
            raise ToolError("SD must be between 0 and 0xFFFFFF")
        return f"{sd:06x}"

    value = str(sd).strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    if not value or any(ch not in "0123456789abcdef" for ch in value):
        raise ToolError("SD must be hexadecimal")
    if len(value) > 6:
        raise ToolError("SD must be at most 6 hex characters")
    return value.zfill(6)


def _validate_dnn(dnn: str) -> str:
    """Validate a DNN or APN name."""
    value = str(dnn).strip()
    if not value:
        raise ToolError("DNN must be a non-empty string")
    return value


@tool
def update_subscriber_slice():
    """Update the default subscriber slice and session DNN in MongoDB.

    Use this when diagnosis indicates the subscriber profile is mapped to the
    wrong slice or service profile.
    """

    async def execute(imsi: str, sst: int, sd: str, dnn: str = "internet") -> str:
        """Update one subscriber's primary slice assignment.

        Args:
            imsi: Subscriber IMSI
            sst: Slice/service type
            sd: Slice differentiator
            dnn: Session DNN/APN to associate with the slice

        Returns:
            Summary of old and new subscriber profile state.
        """
        clean_imsi = _normalize_imsi(imsi)
        clean_sst = _normalize_sst(sst)
        clean_sd = _normalize_sd(sd)
        clean_dnn = _validate_dnn(dnn)

        mongo = sandbox("mongo")
        js = f"""
const collection = db.getSiblingDB("open5gs").subscribers;
const imsi = "{clean_imsi}";
const subscriber = collection.findOne({{ imsi }});
if (!subscriber) {{
  print(JSON.stringify({{ error: "subscriber_not_found", imsi }}));
  quit(0);
}}
const oldProfile = {{
  sst: subscriber.slice?.[0]?.sst ?? null,
  sd: subscriber.slice?.[0]?.sd ?? null,
  dnn: subscriber.slice?.[0]?.session?.[0]?.dnn ?? null
}};
collection.updateOne(
  {{ imsi }},
  {{
    $set: {{
      "slice.0.sst": {clean_sst},
      "slice.0.sd": "{clean_sd}",
      "slice.0.default_indicator": true,
      "slice.0.session.0.name": "{clean_dnn}",
      "slice.0.session.0.dnn": "{clean_dnn}"
    }}
  }}
);
const updated = collection.findOne({{ imsi }});
print(JSON.stringify({{
  imsi,
  old: oldProfile,
  updated: {{
    sst: updated.slice?.[0]?.sst ?? null,
    sd: updated.slice?.[0]?.sd ?? null,
    dnn: updated.slice?.[0]?.session?.[0]?.dnn ?? null
  }}
}}));
"""
        result = await mongo.exec(
            ["mongosh", "--quiet", "--eval", js],
            timeout=15,
        )

        if not result.success:
            record_action(
                tool_name="update_subscriber_slice",
                target=f"subscriber:{clean_imsi}",
                parameters={"sst": clean_sst, "sd": clean_sd, "dnn": clean_dnn},
                success=False,
                restart_required=False,
                risk_class="high",
                details=result.stderr or "MongoDB update failed",
            )
            raise ToolError(f"MongoDB update failed: {result.stderr}")

        try:
            payload = json.loads(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise ToolError(f"Unexpected MongoDB response: {result.stdout}") from exc

        if payload.get("error") == "subscriber_not_found":
            record_action(
                tool_name="update_subscriber_slice",
                target=f"subscriber:{clean_imsi}",
                parameters={"sst": clean_sst, "sd": clean_sd, "dnn": clean_dnn},
                success=False,
                restart_required=False,
                risk_class="high",
                details="Subscriber not found",
            )
            raise ToolError(f"Subscriber '{clean_imsi}' not found")

        record_action(
            tool_name="update_subscriber_slice",
            target=f"subscriber:{clean_imsi}",
            parameters={"sst": clean_sst, "sd": clean_sd, "dnn": clean_dnn},
            old_value=payload.get("old"),
            new_value=payload.get("updated"),
            success=True,
            restart_required=False,
            risk_class="high",
            details="Subscriber slice updated in MongoDB",
        )

        updated = payload.get("updated", {})
        return (
            "Updated subscriber profile:\n"
            f"  IMSI: {clean_imsi}\n"
            f"  Old: {payload.get('old')}\n"
            f"  New: {updated}\n\n"
            "Use trigger_ue_registration() if the UE should re-register with the new profile."
        )

    return execute
