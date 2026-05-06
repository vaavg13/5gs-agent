"""Intent schema helpers for the intent-oriented network slicing benchmark."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SUPPORTED_INTENT_METRICS = {
    "uplink_throughput_mbps": ">=",
    "downlink_throughput_mbps": ">=",
    "max_latency_ms": "<=",
    "max_jitter_ms": "<=",
    "max_packet_loss_pct": "<=",
}

METRIC_ALIASES = {
    "latency_ms_avg": "max_latency_ms",
    "latency_ms_p95": "max_latency_ms",
    "jitter_ms": "max_jitter_ms",
    "packet_loss_pct": "max_packet_loss_pct",
}


class IntentValidationError(ValueError):
    """Raised when an intent document is malformed."""


def _normalize_sd(sd: Any) -> str:
    """Normalize SD to a six-character lowercase hex string."""
    if sd is None:
        raise IntentValidationError("slice.sd is required")

    if isinstance(sd, int):
        if sd < 0 or sd > 0xFFFFFF:
            raise IntentValidationError("slice.sd must be between 0 and 0xFFFFFF")
        return f"{sd:06x}"

    sd_str = str(sd).strip().lower()
    if sd_str.startswith("0x"):
        sd_str = sd_str[2:]
    if not sd_str:
        raise IntentValidationError("slice.sd cannot be empty")
    if any(ch not in "0123456789abcdef" for ch in sd_str):
        raise IntentValidationError(f"slice.sd must be hexadecimal, got '{sd}'")
    if len(sd_str) > 6:
        raise IntentValidationError(f"slice.sd must be at most 6 hex chars, got '{sd}'")
    return sd_str.zfill(6)


def _normalize_slice(slice_config: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Validate and normalize a slice descriptor."""
    if not isinstance(slice_config, dict):
        raise IntentValidationError(f"{field_name} must be a mapping")

    if "sst" not in slice_config:
        raise IntentValidationError(f"{field_name}.sst is required")

    try:
        sst = int(slice_config["sst"])
    except (TypeError, ValueError) as exc:
        raise IntentValidationError(f"{field_name}.sst must be an integer") from exc

    if sst < 0 or sst > 255:
        raise IntentValidationError(f"{field_name}.sst must be between 0 and 255")

    return {
        "sst": sst,
        "sd": _normalize_sd(slice_config.get("sd")),
    }


def _normalize_objective(
    objective: dict[str, Any],
    index: int,
    section: str,
) -> dict[str, Any]:
    """Validate one objective and map aliases to scorer-supported metrics."""
    if not isinstance(objective, dict):
        raise IntentValidationError(f"intent.objectives.{section}[{index}] must be a mapping")

    raw_metric = str(objective.get("metric", "")).strip()
    if not raw_metric:
        raise IntentValidationError(
            f"intent.objectives.{section}[{index}].metric is required"
        )

    ue_id = None
    metric_name = raw_metric
    if "." in raw_metric:
        possible_ue_id, possible_metric = raw_metric.split(".", 1)
        alias_metric = METRIC_ALIASES.get(possible_metric, possible_metric)
        if alias_metric in SUPPORTED_INTENT_METRICS:
            ue_id = possible_ue_id.strip()
            metric_name = possible_metric

    metric = METRIC_ALIASES.get(metric_name, metric_name)
    if metric not in SUPPORTED_INTENT_METRICS:
        supported = ", ".join(sorted(SUPPORTED_INTENT_METRICS))
        raise IntentValidationError(
            f"unsupported metric '{raw_metric}' in intent.objectives.{section}[{index}]. "
            f"Supported metrics: {supported}"
        )

    operator = str(objective.get("op", "")).strip()
    expected_operator = SUPPORTED_INTENT_METRICS[metric]
    if operator != expected_operator:
        raise IntentValidationError(
            f"metric '{raw_metric}' requires operator '{expected_operator}', got '{operator}'"
        )

    value = objective.get("value")
    try:
        normalized_value = float(value)
    except (TypeError, ValueError) as exc:
        raise IntentValidationError(
            f"intent.objectives.{section}[{index}].value must be numeric"
        ) from exc

    normalized_metric = f"{ue_id}.{metric}" if ue_id else metric
    normalized = {
        "metric": normalized_metric,
        "op": operator,
        "value": normalized_value,
    }

    if "weight" in objective:
        try:
            weight = float(objective["weight"])
        except (TypeError, ValueError) as exc:
            raise IntentValidationError(
                f"intent.objectives.{section}[{index}].weight must be numeric"
            ) from exc
        if weight <= 0:
            raise IntentValidationError(
                f"intent.objectives.{section}[{index}].weight must be positive"
            )
        normalized["weight"] = weight

    return normalized


def validate_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize an intent document."""
    if not isinstance(intent, dict):
        raise IntentValidationError("intent must be a mapping")

    normalized = deepcopy(intent)

    service = str(normalized.get("service", "")).strip()
    if not service:
        raise IntentValidationError("intent.service is required")
    normalized["service"] = service

    if "slice" in normalized:
        normalized["slice"] = _normalize_slice(normalized["slice"], "intent.slice")

    if "ues" in normalized:
        if not isinstance(normalized["ues"], list) or not normalized["ues"]:
            raise IntentValidationError("intent.ues must be a non-empty list when provided")
        normalized_ues = []
        for index, ue in enumerate(normalized["ues"]):
            if not isinstance(ue, dict):
                raise IntentValidationError(f"intent.ues[{index}] must be a mapping")
            ue_id = str(ue.get("ue_id", "")).strip()
            role = str(ue.get("role", "")).strip() or "target"
            if not ue_id:
                raise IntentValidationError(f"intent.ues[{index}].ue_id is required")
            normalized_ue = {
                "ue_id": ue_id,
                "role": role,
            }
            service = str(ue.get("service", "")).strip()
            if service:
                normalized_ue["service"] = service
            if "slice" in ue:
                normalized_ue["slice"] = _normalize_slice(
                    ue["slice"], f"intent.ues[{index}].slice"
                )
            if "traffic_profile" in ue:
                if not isinstance(ue["traffic_profile"], dict):
                    raise IntentValidationError(
                        f"intent.ues[{index}].traffic_profile must be a mapping"
                    )
                normalized_ue["traffic_profile"] = deepcopy(ue["traffic_profile"])
            normalized_ues.append(normalized_ue)
        normalized["ues"] = normalized_ues

    objectives = normalized.get("objectives")
    if not isinstance(objectives, dict):
        raise IntentValidationError("intent.objectives is required and must be a mapping")

    normalized_objectives: dict[str, list[dict[str, Any]]] = {"hard": [], "soft": []}
    for section in ("hard", "soft"):
        raw_items = objectives.get(section, [])
        if raw_items is None:
            raw_items = []
        if not isinstance(raw_items, list):
            raise IntentValidationError(f"intent.objectives.{section} must be a list")
        normalized_objectives[section] = [
            _normalize_objective(item, index, section)
            for index, item in enumerate(raw_items)
        ]

    if not normalized_objectives["hard"] and not normalized_objectives["soft"]:
        raise IntentValidationError("intent.objectives must include at least one hard or soft objective")

    normalized["objectives"] = normalized_objectives

    control = normalized.get("control", {})
    if control:
        if not isinstance(control, dict):
            raise IntentValidationError("intent.control must be a mapping")
        normalized_control = {}
        for key in (
            "recovery_deadline_s",
            "stability_window_s",
            "max_actions",
            "max_restarts",
        ):
            if key not in control:
                continue
            try:
                value = int(control[key])
            except (TypeError, ValueError) as exc:
                raise IntentValidationError(f"intent.control.{key} must be an integer") from exc
            if value < 0:
                raise IntentValidationError(f"intent.control.{key} must be non-negative")
            normalized_control[key] = value
        normalized["control"] = normalized_control

    safety = normalized.get("safety", {})
    if safety:
        if not isinstance(safety, dict):
            raise IntentValidationError("intent.safety must be a mapping")
        normalized_safety = {}
        forbidden = safety.get("forbidden_actions", [])
        if forbidden:
            if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
                raise IntentValidationError("intent.safety.forbidden_actions must be a list of strings")
            normalized_safety["forbidden_actions"] = forbidden
        if "allow_shell" in safety:
            normalized_safety["allow_shell"] = bool(safety["allow_shell"])
        normalized["safety"] = normalized_safety

    return normalized


def build_expected_metrics_from_intent(intent: dict[str, Any]) -> dict[str, float]:
    """Extract scorer-compatible thresholds from an intent."""
    normalized = validate_intent(intent)
    expected: dict[str, float] = {}
    for section in ("hard", "soft"):
        for objective in normalized["objectives"][section]:
            metric = objective["metric"]
            expected[metric] = float(objective["value"])
    return expected


def resolve_ue_service(intent: dict[str, Any] | None, ue_id: str | None = None) -> str:
    """Resolve a UE identifier to a sandbox service name."""
    if not intent:
        return ue_id or "ue_premium"

    for ue in intent.get("ues", []):
        if ue_id is not None and ue.get("ue_id") != ue_id:
            continue
        service = str(ue.get("service", "")).strip()
        if service:
            return service
        if ue.get("ue_id"):
            return str(ue["ue_id"])

    return ue_id or "ue_premium"


def target_ue_service(intent: dict[str, Any] | None) -> str:
    """Return the default target UE service for an intent."""
    if intent:
        for ue in intent.get("ues", []):
            if ue.get("role") == "target":
                return resolve_ue_service(intent, ue.get("ue_id"))
        return resolve_ue_service(intent)
    return "ue_premium"


def format_intent_summary(intent: dict[str, Any]) -> str:
    """Render a compact intent summary for the agent prompt.

    Deliberately omits slice identifiers (SST/SD) — the agent must
    discover slice assignments by querying the network.
    """
    normalized = validate_intent(intent)

    lines = [f"Service intent: {normalized['service']}"]

    if normalized.get("ues"):
        lines.append("UE roles:")
        for ue in normalized["ues"]:
            line = f"- {ue['ue_id']} ({ue['role']})"
            if ue.get("service"):
                line += f" service={ue['service']}"
            lines.append(line)

    lines.append("Hard objectives:")
    for objective in normalized["objectives"]["hard"]:
        lines.append(
            f"- {objective['metric']} {objective['op']} {objective['value']}"
        )

    if normalized["objectives"]["soft"]:
        lines.append("Soft objectives:")
        for objective in normalized["objectives"]["soft"]:
            weight = objective.get("weight")
            suffix = f" (weight={weight})" if weight is not None else ""
            lines.append(
                f"- {objective['metric']} {objective['op']} {objective['value']}{suffix}"
            )

    if normalized.get("control"):
        lines.append("Control constraints:")
        for key, value in normalized["control"].items():
            lines.append(f"- {key}: {value}")

    if normalized.get("safety"):
        lines.append("Safety constraints:")
        if normalized["safety"].get("forbidden_actions"):
            for action in normalized["safety"]["forbidden_actions"]:
                lines.append(f"- forbidden action: {action}")
        if "allow_shell" in normalized["safety"]:
            lines.append(f"- allow_shell: {normalized['safety']['allow_shell']}")

    return "\n".join(lines)
