"""SLA compliance scorer for network slicing tasks.

Runs iperf3/ping measurements and evaluates against SLA thresholds
defined in sample metadata.
"""

from __future__ import annotations

import json
import re

from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

# Metric definitions: (measurement_key, operator, failure_default)
METRIC_DEFINITIONS = {
    "uplink_throughput_mbps": ("uplink_mbps", ">=", 0.0),
    "downlink_throughput_mbps": ("downlink_mbps", ">=", 0.0),
    "max_latency_ms": ("latency_ms", "<=", 999.0),
    "max_jitter_ms": ("jitter_ms", "<=", 999.0),
    "max_packet_loss_pct": ("packet_loss_pct", "<=", 100.0),
}


async def _check_connectivity() -> tuple[bool, str]:
    """Check if UE can reach iperf3 server."""
    ue = sandbox("ue")
    result = await ue.exec(
        ["ping", "-c", "3", "-I", "uesimtun0", "iperf3-server"],
        timeout=15,
    )
    if result.success:
        return True, "Connectivity OK"
    return False, result.stderr or "Ping failed"


async def _measure_throughput(direction: str, duration: int = 10) -> tuple[bool, float]:
    """Run iperf3 throughput test."""
    ue = sandbox("ue")

    cmd = [
        "iperf3",
        "-c",
        "iperf3-server",
        "-t",
        str(duration),
        "-J",
        "--bind-dev",
        "uesimtun0",
    ]
    if direction == "downlink":
        cmd.append("-R")

    result = await ue.exec(cmd, timeout=duration + 30)

    if not result.success:
        return False, 0.0

    try:
        data = json.loads(result.stdout)
        end = data.get("end", {})
        sum_key = "sum_received" if direction == "downlink" else "sum_sent"
        bits_per_second = end.get(sum_key, {}).get("bits_per_second", 0)
        return True, bits_per_second / 1_000_000
    except (json.JSONDecodeError, KeyError):
        return False, 0.0


async def _measure_latency(count: int = 100) -> tuple[bool, float, float, float]:
    """Run ping latency test. Returns (success, avg_latency, jitter, loss_pct)."""
    ue = sandbox("ue")

    result = await ue.exec(
        ["ping", "-c", str(count), "-I", "uesimtun0", "iperf3-server"],
        timeout=count + 30,
    )

    if not result.success:
        return False, 999.0, 999.0, 100.0

    output = result.stdout

    # Extract packet loss
    loss_match = re.search(r"(\d+)% packet loss", output)
    loss_pct = float(loss_match.group(1)) if loss_match else 100.0

    # Extract RTT stats
    rtt_match = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        output,
    )
    if rtt_match:
        _, avg_rtt, _, mdev = rtt_match.groups()
        return True, float(avg_rtt), float(mdev), loss_pct

    return False, 999.0, 999.0, loss_pct


def _check_threshold(measured: float, operator: str, threshold: float) -> bool:
    """Check if measured value meets threshold."""
    if operator == ">=":
        return measured >= threshold
    return measured <= threshold


@scorer(metrics=[mean(), stderr()])
def sla_compliance_scorer():
    """Score based on iperf3/ping measurements against SLA from metadata."""

    async def score(state: TaskState, target: Target) -> Score:
        # Get thresholds from metadata
        expected = state.metadata.get("expected_metrics", {})
        if not expected:
            return Score(
                value=0.0,
                answer="Missing expected_metrics",
                explanation="Sample metadata must include 'expected_metrics'",
            )

        # Check connectivity first
        connected, msg = await _check_connectivity()
        if not connected:
            return Score(
                value=0.0,
                answer="Connectivity failed",
                explanation=f"UE cannot reach iperf3-server: {msg}",
            )

        # Collect measurements
        measurements = {}

        ul_ok, ul_mbps = await _measure_throughput("uplink")
        measurements["uplink_mbps"] = ul_mbps if ul_ok else 0.0

        dl_ok, dl_mbps = await _measure_throughput("downlink")
        measurements["downlink_mbps"] = dl_mbps if dl_ok else 0.0

        lat_ok, latency, jitter, loss = await _measure_latency()
        measurements["latency_ms"] = latency
        measurements["jitter_ms"] = jitter
        measurements["packet_loss_pct"] = loss

        # Evaluate against thresholds
        compliance = {}
        for threshold_key, (measurement_key, operator, default) in METRIC_DEFINITIONS.items():
            if threshold_key not in expected:
                continue
            threshold = expected[threshold_key]
            measured = measurements.get(measurement_key, default)
            compliance[threshold_key] = _check_threshold(measured, operator, threshold)

        # Calculate score
        num_passing = sum(compliance.values())
        total = len(compliance)
        overall_score = num_passing / total if total > 0 else 0.0

        # Build explanation
        lines = []
        for threshold_key, (measurement_key, operator, _) in METRIC_DEFINITIONS.items():
            if threshold_key not in expected:
                continue
            threshold = expected[threshold_key]
            measured = measurements.get(measurement_key, 0)
            status = "PASS" if compliance.get(threshold_key) else "FAIL"
            lines.append(f"{threshold_key}: {measured:.2f} {operator} {threshold} [{status}]")

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
            },
        )

    return score
