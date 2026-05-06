"""Observability tools for intent-driven network slicing tasks.

Reads from the background metrics collector CSV rather than running
ad-hoc iperf3/ping measurements, avoiding iperf3 server contention.
"""

from __future__ import annotations

import json

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

METRICS_CSV_PATH = "/tmp/metrics.csv"


async def _read_recent_metrics(
    ue, n_rows: int = 10
) -> list[dict[str, float | str]]:
    result = await ue.exec(
        ["tail", "-n", str(n_rows), METRICS_CSV_PATH], timeout=5
    )
    if not result.success:
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
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
    return rows


@tool
def measure_ue_throughput():
    """Read UE throughput from the continuous monitoring stream.

    Returns average throughput over a recent time window from the
    background iperf3 stream running through the 5G data plane.
    """

    async def execute(
        ue_service: str = "ue_premium",
        direction: str = "downlink",
        duration: int = 10,
    ) -> str:
        """Read throughput from the monitoring stream.

        Args:
            ue_service: UE container to read metrics from
            direction: Reported direction (the stream measures downlink)
            duration: Number of recent seconds to average over (default: 10)

        Returns:
            Throughput measurement results.
        """
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            return f"Invalid duration value: '{duration}'. Must be a positive integer."
        duration = max(1, min(duration, 300))

        if not isinstance(ue_service, str) or not ue_service.strip():
            return "Invalid ue_service: must be a non-empty string"
        ue_service = ue_service.strip()

        ue = sandbox(ue_service)
        rows = await _read_recent_metrics(ue, n_rows=duration)
        if not rows:
            raise ToolError(
                f"No metrics available on {ue_service}. "
                "The monitoring stream may not be running on this UE."
            )

        throughputs = [r["throughput_mbps"] for r in rows]
        avg = sum(throughputs) / len(throughputs)
        latest = throughputs[-1]

        return (
            f"Throughput (downlink, continuous stream): {avg:.2f} Mbps (avg over {len(rows)}s)\n"
            f"UE Service: {ue_service}\n"
            f"Latest: {latest:.2f} Mbps\n"
            f"Min: {min(throughputs):.2f} Mbps\n"
            f"Max: {max(throughputs):.2f} Mbps\n"
            f"Window: {rows[0]['timestamp']} to {rows[-1]['timestamp']}"
        )

    return execute


@tool
def measure_ue_latency():
    """Read UE latency from the continuous monitoring stream.

    Returns latency, jitter, and packet loss statistics over a recent
    time window from the background ping running through the 5G data plane.
    """

    async def execute(
        ue_service: str = "ue_premium",
        target: str = "",
        count: int = 30,
    ) -> str:
        """Read latency from the monitoring stream.

        Args:
            ue_service: UE container to read metrics from
            target: Informational only (each UE pings its dedicated endpoint)
            count: Number of recent seconds to average over (default: 30)

        Returns:
            Latency statistics.
        """
        try:
            count = int(count)
        except (ValueError, TypeError):
            return f"Invalid count value: '{count}'. Must be a positive integer."
        count = max(1, min(count, 1000))

        if not isinstance(ue_service, str) or not ue_service.strip():
            return "Invalid ue_service: must be a non-empty string"
        ue_service = ue_service.strip()

        ue = sandbox(ue_service)
        rows = await _read_recent_metrics(ue, n_rows=count)
        if not rows:
            raise ToolError(
                f"No metrics available on {ue_service}. "
                "The monitoring stream may not be running on this UE."
            )

        latencies = [r["latency_ms"] for r in rows]
        jitters = [r["jitter_ms"] for r in rows]
        losses = [r["packet_loss_pct"] for r in rows]

        avg_lat = sum(latencies) / len(latencies)
        avg_jit = sum(jitters) / len(jitters)
        avg_loss = sum(losses) / len(losses)

        return (
            f"=== Latency Measurement ({ue_service}, continuous stream, {len(rows)}s window) ===\n"
            f"Latency (avg): {avg_lat:.3f} ms\n"
            f"Latency (min): {min(latencies):.3f} ms\n"
            f"Latency (max): {max(latencies):.3f} ms\n"
            f"Jitter (avg): {avg_jit:.3f} ms\n"
            f"Packet Loss: {avg_loss:.2f}%\n"
            f"Window: {rows[0]['timestamp']} to {rows[-1]['timestamp']}"
        )

    return execute


@tool
def query_prometheus():
    """Query Prometheus metrics.

    Access Open5GS metrics exposed by AMF and SMF.
    Requires observability profile to be enabled.
    """

    async def execute(query: str) -> str:
        """Execute a PromQL query.

        Args:
            query: PromQL query string (e.g., "amf_n1_message_total")

        Returns:
            Query results.

        Example queries:
            - amf_registered_subscribers
            - amf_n1_message_total
            - smf_pdu_session_total
        """
        if not isinstance(query, str) or not query.strip():
            return "Invalid query: must be a non-empty PromQL string"

        query = query.strip()

        try:
            prometheus = sandbox("prometheus")
        except ValueError:
            return "Prometheus is not available. The observability profile must be enabled in the scenario configuration."

        result = await prometheus.exec(
            [
                "wget",
                "-qO-",
                f"http://localhost:9090/api/v1/query?query={query}",
            ],
            timeout=10,
        )

        if not result.success:
            raise ToolError(f"Prometheus query failed: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            if data.get("status") == "success":
                results = data.get("data", {}).get("result", [])
                if not results:
                    return f"Query '{query}' returned no results"

                lines = [f"=== Query: {query} ==="]
                for r in results:
                    metric = r.get("metric", {})
                    value = r.get("value", [None, "?"])[1]
                    lines.append(f"{metric}: {value}")
                return "\n".join(lines)
            else:
                return f"Query error: {data.get('error', 'unknown')}"
        except json.JSONDecodeError:
            return f"Raw output:\n{result.stdout}"

    return execute
