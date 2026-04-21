"""Structured diagnosis helpers for intent-oriented network slicing tasks."""

from __future__ import annotations

import json
from typing import Any

import yaml


def _normalize_sd(sd: Any) -> str | None:
    """Normalize SD values from config and subscriber sources."""
    if sd is None:
        return None
    if isinstance(sd, int):
        return f"{sd:06x}"
    sd_str = str(sd).strip().lower()
    if sd_str.startswith("0x"):
        sd_str = sd_str[2:]
    if not sd_str:
        return None
    if any(ch not in "0123456789abcdef" for ch in sd_str):
        return None
    return sd_str.zfill(6)


def _slice_matches(candidate: dict[str, Any], expected_slice: dict[str, Any]) -> bool:
    """Return True when a slice matches expected SST/SD."""
    return (
        int(candidate.get("sst", -1)) == int(expected_slice["sst"])
        and _normalize_sd(candidate.get("sd")) == _normalize_sd(expected_slice["sd"])
    )


async def collect_diagnostic_snapshot(
    *,
    ue_service: str = "ue_premium",
    imsi: str | None = None,
    expected_slice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect a minimal structured snapshot across control and data plane."""
    from inspect_ai.util import sandbox

    snapshot: dict[str, Any] = {
        "expected_slice": expected_slice,
        "ue": {},
        "subscriber": {},
        "amf": {},
        "nrf": {},
        "upf": {},
    }

    ue = sandbox(ue_service)
    upf = sandbox("upf")
    amf = sandbox("amf")
    nrf = sandbox("nrf")
    mongo = sandbox("mongo")

    ue_status = await ue.exec(["ip", "addr", "show", "uesimtun0"], timeout=5)
    snapshot["ue"]["pdu_session_active"] = bool(ue_status.success and "inet " in ue_status.stdout)
    snapshot["ue"]["interface_output"] = ue_status.stdout.strip() if ue_status.stdout else ""
    snapshot["ue"]["service"] = ue_service

    route_result = await ue.exec(["ip", "route"], timeout=5)
    snapshot["ue"]["routes"] = route_result.stdout.strip() if route_result.success else ""

    tc_result = await upf.exec(["sh", "-c", "tc qdisc show dev ogstun"], timeout=5)
    qdisc_output = tc_result.stdout.strip() if tc_result.success else ""
    snapshot["upf"]["qdisc_output"] = qdisc_output
    # Healthy service-class shaping uses HTB plus per-class delay. Reserve the
    # "impairment" signal for packet loss or more disruptive netem behaviors.
    snapshot["upf"]["transport_impairment_detected"] = any(
        token in qdisc_output for token in (" loss ", "corrupt", "reorder", "duplicate")
    )

    amf_result = await amf.exec(["cat", "/opt/open5gs/etc/open5gs/amf.yaml"], timeout=5)
    if amf_result.success:
        amf_data = yaml.safe_load(amf_result.stdout) or {}
        slices = []
        for plmn in amf_data.get("amf", {}).get("plmn_support", []):
            for snssai in plmn.get("s_nssai", []):
                slices.append(
                    {
                        "sst": snssai.get("sst"),
                        "sd": _normalize_sd(snssai.get("sd")),
                    }
                )
        snapshot["amf"]["configured_slices"] = slices
    else:
        snapshot["amf"]["configured_slices"] = []
        snapshot["amf"]["error"] = amf_result.stderr.strip()

    nrf_result = await nrf.exec(
        ["curl", "-sf", "http://localhost:7777/nnrf-nfm/v1/nf-instances"],
        timeout=10,
    )
    snapshot["nrf"]["query_success"] = bool(nrf_result.success)
    snapshot["nrf"]["raw"] = nrf_result.stdout.strip() if nrf_result.success else ""

    if imsi:
        mongo_cmd = (
            "mongosh open5gs --quiet --eval "
            f"'JSON.stringify(db.subscribers.findOne({{imsi: \"{imsi}\"}}))'"
        )
    else:
        mongo_cmd = (
            "mongosh open5gs --quiet --eval "
            "'JSON.stringify(db.subscribers.find({}).toArray())'"
        )

    mongo_result = await mongo.exec(["sh", "-c", mongo_cmd], timeout=10)
    if mongo_result.success and mongo_result.stdout.strip():
        try:
            parsed = json.loads(mongo_result.stdout)
        except json.JSONDecodeError:
            parsed = None
        snapshot["subscriber"]["records"] = parsed
    else:
        snapshot["subscriber"]["records"] = None
        snapshot["subscriber"]["error"] = mongo_result.stderr.strip()

    return snapshot


def infer_root_causes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate ranked root-cause hypotheses from a diagnostic snapshot."""
    hypotheses: list[dict[str, Any]] = []

    if snapshot.get("upf", {}).get("transport_impairment_detected"):
        hypotheses.append(
            {
                "label": "transport_impairment_upf",
                "confidence": "high",
                "evidence": ["UPF ogstun has active tc qdisc impairment rules"],
            }
        )

    if not snapshot.get("ue", {}).get("pdu_session_active"):
        hypotheses.append(
            {
                "label": "ue_registration_or_pdu_session_failure",
                "confidence": "high",
                "evidence": ["uesimtun0 is missing or has no assigned IP address"],
            }
        )

    if not snapshot.get("nrf", {}).get("query_success"):
        hypotheses.append(
            {
                "label": "control_plane_registration_issue",
                "confidence": "medium",
                "evidence": ["NRF NF registry query failed"],
            }
        )

    expected_slice = snapshot.get("expected_slice")
    if expected_slice:
        configured_slices = snapshot.get("amf", {}).get("configured_slices", [])
        if configured_slices and not any(
            _slice_matches(candidate, expected_slice) for candidate in configured_slices
        ):
            hypotheses.append(
                {
                    "label": "slice_config_mismatch",
                    "confidence": "high",
                    "evidence": [
                        "Expected slice is not present in AMF plmn_support configuration"
                    ],
                }
            )

        subscriber_records = snapshot.get("subscriber", {}).get("records")
        if isinstance(subscriber_records, dict):
            subscriber_records = [subscriber_records]
        if isinstance(subscriber_records, list) and subscriber_records:
            if not any(
                int(record.get("sst", -1)) == int(expected_slice["sst"])
                and _normalize_sd(record.get("sd")) == _normalize_sd(expected_slice["sd"])
                for record in subscriber_records
                if isinstance(record, dict)
            ):
                hypotheses.append(
                    {
                        "label": "subscriber_profile_mismatch",
                        "confidence": "medium",
                        "evidence": [
                            "Subscriber records do not match the expected slice assignment"
                        ],
                    }
                )

    if not hypotheses and snapshot.get("ue", {}).get("pdu_session_active"):
        hypotheses.append(
            {
                "label": "data_plane_connectivity_issue",
                "confidence": "low",
                "evidence": [
                    "UE has an active PDU session but no stronger root cause was inferred"
                ],
            }
        )

    if not hypotheses:
        hypotheses.append(
            {
                "label": "unknown",
                "confidence": "low",
                "evidence": ["No clear diagnosis could be inferred from the snapshot"],
            }
        )

    confidence_order = {"high": 3, "medium": 2, "low": 1}
    hypotheses.sort(key=lambda item: confidence_order.get(item["confidence"], 0), reverse=True)
    return hypotheses


def format_diagnosis_report(snapshot: dict[str, Any], hypotheses: list[dict[str, Any]]) -> str:
    """Render a human-readable diagnosis report."""
    lines = ["=== Structured Diagnosis ==="]

    ue_active = snapshot.get("ue", {}).get("pdu_session_active")
    lines.append(f"UE PDU session active: {ue_active}")

    qdisc_output = snapshot.get("upf", {}).get("qdisc_output", "")
    lines.append(
        "UPF transport impairment detected: "
        f"{snapshot.get('upf', {}).get('transport_impairment_detected', False)}"
    )
    if qdisc_output:
        lines.append(f"UPF qdisc: {qdisc_output}")

    configured_slices = snapshot.get("amf", {}).get("configured_slices", [])
    if configured_slices:
        lines.append(f"AMF configured slices: {configured_slices}")

    lines.append("Hypotheses:")
    for hypothesis in hypotheses:
        evidence = "; ".join(hypothesis.get("evidence", []))
        lines.append(
            f"- {hypothesis['label']} (confidence={hypothesis['confidence']}): {evidence}"
        )

    return "\n".join(lines)
