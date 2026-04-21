"""SLA compliance scorer for network slicing tasks.

Reads measurements from the background metrics collector CSV and
evaluates against SLA thresholds defined in sample metadata.
Exports the full time-series in the Score metadata for post-experiment analysis.
"""

from __future__ import annotations

import re

from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

METRICS_CSV_PATH = "/tmp/metrics.csv"

METRIC_DEFINITIONS = {
    "uplink_throughput_mbps": ("uplink_mbps", ">=", 0.0),
    "downlink_throughput_mbps": ("downlink_mbps", ">=", 0.0),
    "max_latency_ms": ("latency_ms", "<=", 999.0),
    "max_jitter_ms": ("jitter_ms", "<=", 999.0),
    "max_packet_loss_pct": ("packet_loss_pct", "<=", 100.0),
}


async def _read_all_metrics() -> tuple[list[dict], str]:
    """Read full CSV from UE container. Returns (parsed_rows, raw_csv)."""
    ue = sandbox("ue")
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


async def _check_connectivity() -> tuple[bool, str]:
    ue = sandbox("ue")
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
        if not expected:
            return Score(
                value=0.0,
                answer="Missing expected_metrics",
                explanation="Sample metadata must include 'expected_metrics'",
            )

        connected, msg = await _check_connectivity()
        if not connected:
            return Score(
                value=0.0,
                answer="Connectivity failed",
                explanation=f"UE cannot reach iperf3-server: {msg}",
            )

        all_rows, raw_csv = await _read_all_metrics()
        if not all_rows:
            return Score(
                value=0.0,
                answer="No metrics data",
                explanation="Metrics collector CSV is empty or missing",
            )

        # Use last 30 seconds for SLA evaluation
        window = all_rows[-30:] if len(all_rows) >= 30 else all_rows

        throughputs = [r["throughput_mbps"] for r in window]
        latencies = [r["latency_ms"] for r in window]
        jitters = [r["jitter_ms"] for r in window]
        losses = [r["packet_loss_pct"] for r in window]

        avg_tp = sum(throughputs) / len(throughputs)
        avg_lat = sum(latencies) / len(latencies)
        avg_jit = sum(jitters) / len(jitters)
        avg_loss = sum(losses) / len(losses)

        measurements = {
            "uplink_mbps": avg_tp,
            "downlink_mbps": avg_tp,
            "latency_ms": avg_lat,
            "jitter_ms": avg_jit,
            "packet_loss_pct": avg_loss,
        }

        compliance = {}
        for threshold_key, (measurement_key, operator, default) in METRIC_DEFINITIONS.items():
            if threshold_key not in expected:
                continue
            threshold = expected[threshold_key]
            measured = measurements.get(measurement_key, default)
            compliance[threshold_key] = _check_threshold(measured, operator, threshold)

        num_passing = sum(compliance.values())
        total = len(compliance)
        overall_score = num_passing / total if total > 0 else 0.0

        lines = []
        for threshold_key, (measurement_key, operator, _) in METRIC_DEFINITIONS.items():
            if threshold_key not in expected:
                continue
            threshold = expected[threshold_key]
            measured = measurements.get(measurement_key, 0)
            status = "PASS" if compliance.get(threshold_key) else "FAIL"
            lines.append(f"{threshold_key}: {measured:.2f} {operator} {threshold} [{status}]")

        lines.append(f"Evaluation window: last {len(window)}s of {len(all_rows)}s total")

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
                "measurements": measurements,
                "thresholds": expected,
                "compliance": compliance,
                "metrics_csv": raw_csv,
                "total_samples": len(all_rows),
            },
        )

    return score
