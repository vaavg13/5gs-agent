"""SLA compliance scorer for network slicing tasks.

Runs iperf3/ping measurements and evaluates against SLA thresholds
defined in sample metadata or derived from a formal intent.
"""

from __future__ import annotations

import json
import re

from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox, store_as

from action_journal import ActionJournal
from intents import build_expected_metrics_from_intent
from intents import resolve_ue_service, target_ue_service
from tools._ue_path import prepare_tunnel_path

# Metric definitions: (measurement_key, operator, failure_default)
METRIC_DEFINITIONS = {
    "uplink_throughput_mbps": ("uplink_mbps", ">=", 0.0),
    "downlink_throughput_mbps": ("downlink_mbps", ">=", 0.0),
    "max_latency_ms": ("latency_ms", "<=", 999.0),
    "max_jitter_ms": ("jitter_ms", "<=", 999.0),
    "max_packet_loss_pct": ("packet_loss_pct", "<=", 100.0),
}


def _parse_metric_target(metric_key: str, intent: dict | None) -> tuple[str, str]:
    """Split a metric key into UE service and normalized metric name."""
    if "." in metric_key:
        ue_id, metric_name = metric_key.split(".", 1)
        return resolve_ue_service(intent, ue_id), metric_name
    return target_ue_service(intent), metric_key


async def _check_connectivity(ue_service: str) -> tuple[bool, str]:
    """Check if UE can reach iperf3 server."""
    ue = sandbox(ue_service)
    try:
        target_ip, tunnel_ip = await prepare_tunnel_path(ue, "iperf3-server")
    except Exception as exc:
        return False, str(exc)
    result = await ue.exec(["ping", "-c", "3", "-I", tunnel_ip, target_ip], timeout=15)
    if result.success:
        return True, "Connectivity OK"
    return False, result.stderr or "Ping failed"


async def _measure_throughput(
    ue_service: str,
    direction: str,
    duration: int = 10,
) -> tuple[bool, float]:
    """Run iperf3 throughput test."""
    ue = sandbox(ue_service)
    try:
        target_ip, tunnel_ip = await prepare_tunnel_path(ue, "iperf3-server")
    except Exception:
        return False, 0.0

    cmd = [
        "iperf3",
        "-c",
        target_ip,
        "-t",
        str(duration),
        "-J",
        "-B",
        tunnel_ip,
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


async def _measure_latency(
    ue_service: str,
    count: int = 30,
) -> tuple[bool, float, float, float]:
    """Run ping latency test. Returns (success, avg_latency, jitter, loss_pct)."""
    ue = sandbox(ue_service)
    try:
        target_ip, tunnel_ip = await prepare_tunnel_path(ue, "iperf3-server")
    except Exception:
        return False, 999.0, 999.0, 100.0

    result = await ue.exec(
        ["ping", "-c", str(count), "-I", tunnel_ip, target_ip],
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
        # Get thresholds from metadata or derive them from formal intent
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

        measurements_by_service: dict[str, dict[str, float]] = {}
        for ue_service in sorted(required_services):
            measurements = {}
            ul_ok, ul_mbps = await _measure_throughput(ue_service, "uplink")
            measurements["uplink_mbps"] = ul_mbps if ul_ok else 0.0

            dl_ok, dl_mbps = await _measure_throughput(ue_service, "downlink")
            measurements["downlink_mbps"] = dl_mbps if dl_ok else 0.0

            lat_ok, latency, jitter, loss = await _measure_latency(ue_service)
            measurements["latency_ms"] = latency
            measurements["jitter_ms"] = jitter
            measurements["packet_loss_pct"] = loss
            measurements_by_service[ue_service] = measurements

        # Evaluate against thresholds
        compliance = {}
        for expected_key, threshold in expected.items():
            ue_service, normalized_metric = _parse_metric_target(expected_key, intent)
            measurement_key, operator, default = METRIC_DEFINITIONS[normalized_metric]
            measured = measurements_by_service.get(ue_service, {}).get(measurement_key, default)
            compliance[expected_key] = _check_threshold(measured, operator, threshold)

        # Calculate score
        num_passing = sum(compliance.values())
        total = len(compliance)
        overall_score = num_passing / total if total > 0 else 0.0

        # Build explanation
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
            },
        )

    return score
