"""SLA compliance scorer for intent-driven network slicing tasks.

Reads measurements from the background metrics collector CSV and
evaluates against SLA thresholds defined in sample metadata or formal intent.
Exports the full time-series in the Score metadata for post-experiment analysis.
"""

from __future__ import annotations

from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox, store_as

from action_journal import ActionJournal
from intents import build_expected_metrics_from_intent
from intents import resolve_ue_service, target_ue_service

METRICS_CSV_PATH = "/tmp/metrics.csv"

METRIC_DEFINITIONS = {
    "uplink_throughput_mbps": ("uplink_mbps", ">=", 0.0),
    "downlink_throughput_mbps": ("downlink_mbps", ">=", 0.0),
    "max_latency_ms": ("latency_ms", "<=", 999.0),
    "max_jitter_ms": ("jitter_ms", "<=", 999.0),
    "max_packet_loss_pct": ("packet_loss_pct", "<=", 100.0),
}


def _parse_metric_target(metric_key: str, intent: dict | None) -> tuple[str, str]:
    if "." in metric_key:
        ue_id, metric_name = metric_key.split(".", 1)
        return resolve_ue_service(intent, ue_id), metric_name
    return target_ue_service(intent), metric_key


async def _read_all_metrics(ue_service: str) -> tuple[list[dict], str]:
    ue = sandbox(ue_service)
    result = await ue.exec(["cat", METRICS_CSV_PATH], timeout=10)
    if not result.success:
        return [], ""

    raw_csv = result.stdout
    rows = []
    for line in raw_csv.strip().split("\n"):
        parts = line.split(",")
        if len(parts) != 5 or parts[0] == "timestamp":
            continue
        try:
            rows.append(
                {
                    "timestamp": parts[0],
                    "throughput_mbps": float(parts[1]),
                    "latency_ms": float(parts[2]),
                    "jitter_ms": float(parts[3]),
                    "packet_loss_pct": float(parts[4]),
                }
            )
        except ValueError:
            continue
    return rows, raw_csv


async def _check_connectivity(ue_service: str) -> tuple[bool, str]:
    ue = sandbox(ue_service)
    result = await ue.exec(
        ["ping", "-c", "3", "-I", "uesimtun0", "iperf3-server"],
        timeout=15,
    )
    if result.success:
        return True, "Connectivity OK"
    return False, result.stderr or "Ping failed"


def _check_threshold(measured: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return measured >= threshold
    return measured <= threshold


@scorer(metrics=[mean(), stderr()])
def sla_compliance_scorer():
    """Score based on continuous monitoring CSV against SLA from metadata."""

    async def score(state: TaskState, target: Target) -> Score:
        expected = state.metadata.get("expected_metrics", {})
        intent = state.metadata.get("intent")
        if not expected and intent:
            expected = build_expected_metrics_from_intent(intent)
        if not expected:
            return Score(
                value=0.0,
                answer="Missing expected metrics",
                explanation="Sample metadata must include 'expected_metrics' or a valid 'intent'",
            )

        required_services = {
            _parse_metric_target(metric_key, intent)[0]
            for metric_key in expected
        }

        connectivity_failures = []
        for ue_service in sorted(required_services):
            connected, msg = await _check_connectivity(ue_service)
            if not connected:
                connectivity_failures.append(f"{ue_service}: {msg}")

        if connectivity_failures:
            return Score(
                value=0.0,
                answer="Connectivity failed",
                explanation="; ".join(connectivity_failures),
            )

        csv_by_service: dict[str, str] = {}
        measurements_by_service: dict[str, dict[str, float]] = {}
        for ue_service in sorted(required_services):
            all_rows, raw_csv = await _read_all_metrics(ue_service)
            csv_by_service[ue_service] = raw_csv

            window = all_rows[-30:] if len(all_rows) >= 30 else all_rows
            if not window:
                measurements_by_service[ue_service] = {
                    "uplink_mbps": 0.0,
                    "downlink_mbps": 0.0,
                    "latency_ms": 999.0,
                    "jitter_ms": 999.0,
                    "packet_loss_pct": 100.0,
                }
                continue

            throughputs = [r["throughput_mbps"] for r in window]
            latencies = [r["latency_ms"] for r in window]
            jitters = [r["jitter_ms"] for r in window]
            losses = [r["packet_loss_pct"] for r in window]

            avg_tp = sum(throughputs) / len(throughputs)
            measurements_by_service[ue_service] = {
                "uplink_mbps": avg_tp,
                "downlink_mbps": avg_tp,
                "latency_ms": sum(latencies) / len(latencies),
                "jitter_ms": sum(jitters) / len(jitters),
                "packet_loss_pct": sum(losses) / len(losses),
            }

        compliance = {}
        for expected_key, threshold in expected.items():
            ue_service, normalized_metric = _parse_metric_target(expected_key, intent)
            measurement_key, operator, default = METRIC_DEFINITIONS[normalized_metric]
            measured = measurements_by_service.get(ue_service, {}).get(measurement_key, default)
            compliance[expected_key] = _check_threshold(measured, operator, threshold)

        num_passing = sum(compliance.values())
        total = len(compliance)
        overall_score = num_passing / total if total > 0 else 0.0

        lines = []
        for expected_key, threshold in expected.items():
            ue_service, normalized_metric = _parse_metric_target(expected_key, intent)
            measurement_key, operator, _ = METRIC_DEFINITIONS[normalized_metric]
            measured = measurements_by_service.get(ue_service, {}).get(measurement_key, 0)
            status = "PASS" if compliance.get(expected_key) else "FAIL"
            lines.append(
                f"{expected_key}: {measured:.2f} {operator} {threshold} [{status}]"
            )

        journal = store_as(ActionJournal)
        restart_count = sum(1 for action in journal.actions if action.tool_name == "restart_service")
        lines.append(f"restart_count: {restart_count}")
        lines.append(f"action_count: {len(journal.actions)}")

        answer = (
            "All SLA requirements satisfied"
            if num_passing == total
            else f"{num_passing}/{total} SLA metrics met"
        )

        return Score(
            value=overall_score,
            answer=answer,
            explanation="\n".join(lines),
            metadata={
                "measurements": measurements_by_service,
                "thresholds": expected,
                "compliance": compliance,
                "intent": intent,
                "action_count": len(journal.actions),
                "restart_count": restart_count,
                "metrics_csv": csv_by_service,
                "action_journal": [
                    a.model_dump(mode="json") for a in journal.actions
                ],
            },
        )

    return score
