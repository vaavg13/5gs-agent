"""Observability tools for network slicing tasks.

Metrics collection, performance measurement, and monitoring tools.
"""

from __future__ import annotations

import json
import re

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

from ._ue_path import prepare_tunnel_path


@tool
def measure_ue_throughput():
    """Measure UE throughput using iperf3.

    Runs iperf3 tests through the 5G data plane (uesimtun0 interface).
    """

    async def execute(
        ue_service: str = "ue_premium",
        direction: str = "downlink",
        duration: int = 10,
    ) -> str:
        """Run iperf3 throughput test.

        Args:
            ue_service: UE container that should run the measurement
            direction: Test direction ('uplink' or 'downlink')
            duration: Test duration in seconds (default: 10)

        Returns:
            Throughput measurement results.
        """
        # Validate direction parameter
        if not isinstance(direction, str):
            return f"Invalid direction type: expected string, got {type(direction).__name__}"

        direction = direction.lower().strip()
        if direction not in ("uplink", "downlink"):
            return "Invalid direction: must be 'uplink' or 'downlink'"

        # Validate duration parameter
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            return f"Invalid duration value: '{duration}'. Must be a positive integer."

        if duration < 1 or duration > 300:
            return f"Invalid duration value: {duration}. Must be between 1 and 300."

        if not isinstance(ue_service, str) or not ue_service.strip():
            return "Invalid ue_service: must be a non-empty string"
        ue_service = ue_service.strip()

        ue = sandbox(ue_service)

        target_ip, tunnel_ip = await prepare_tunnel_path(ue, "iperf3-server")

        ping_result = await ue.exec(
            ["ping", "-c", "1", "-I", tunnel_ip, target_ip],
            timeout=10,
        )
        if not ping_result.success:
            raise ToolError("Cannot reach iperf3-server. Check PDU session.")

        # Build iperf3 command
        cmd = [
            "iperf3",
            "-c",
            target_ip,
            "-t",
            str(duration),
            "-J",  # JSON output
            "-B",
            tunnel_ip,
        ]

        if direction == "uplink":
            pass  # Default is upload
        else:
            cmd.append("-R")  # Reverse mode for download

        result = await ue.exec(cmd, timeout=duration + 30)

        if not result.success:
            raise ToolError(f"iperf3 failed: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            end = data.get("end", {})
            sum_data = end.get("sum_received" if direction == "downlink" else "sum_sent", {})
            bits_per_second = sum_data.get("bits_per_second", 0)
            mbps = bits_per_second / 1_000_000

            return (
                f"Throughput ({direction}): {mbps:.2f} Mbps\n"
                f"UE Service: {ue_service}\n"
                f"Target IP: {target_ip}\n"
                f"Duration: {duration}s\n"
                f"Bytes transferred: {sum_data.get('bytes', 0):,}"
            )
        except json.JSONDecodeError:
            return f"Raw output:\n{result.stdout}"

    return execute


@tool
def measure_ue_latency():
    """Measure UE latency using ping.

    Measures RTT, jitter, and packet loss through the 5G data plane.
    """

    async def execute(
        ue_service: str = "ue_premium",
        target: str = "iperf3-server",
        count: int = 100,
    ) -> str:
        """Run ping latency test.

        Args:
            ue_service: UE container that should run the latency probe
            target: Target host (default: iperf3-server)
            count: Number of pings (default: 100)

        Returns:
            Latency statistics.
        """
        # Validate target parameter
        if not isinstance(target, str) or not target.strip():
            return "Invalid target: must be a non-empty string"

        target = target.strip()

        # Validate count parameter
        try:
            count = int(count)
        except (ValueError, TypeError):
            return f"Invalid count value: '{count}'. Must be a positive integer."

        if count < 1 or count > 1000:
            return f"Invalid count value: {count}. Must be between 1 and 1000."

        if not isinstance(ue_service, str) or not ue_service.strip():
            return "Invalid ue_service: must be a non-empty string"
        ue_service = ue_service.strip()

        ue = sandbox(ue_service)
        target_ip, tunnel_ip = await prepare_tunnel_path(ue, target)

        result = await ue.exec(
            ["ping", "-c", str(count), "-I", tunnel_ip, target_ip],
            timeout=count + 30,
        )

        if not result.success:
            raise ToolError(f"Ping failed: {result.stderr or result.stdout}")

        output = result.stdout

        # Parse ping statistics
        lines = [f"=== Latency Measurement ({ue_service}) ===", f"Target IP: {target_ip}"]

        # Extract packet loss
        loss_match = re.search(r"(\d+)% packet loss", output)
        if loss_match:
            lines.append(f"Packet Loss: {loss_match.group(1)}%")

        # Extract RTT stats (min/avg/max/mdev)
        rtt_match = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
            output,
        )
        if rtt_match:
            min_rtt, avg_rtt, max_rtt, mdev = rtt_match.groups()
            lines.append(f"Latency (avg): {avg_rtt} ms")
            lines.append(f"Latency (min): {min_rtt} ms")
            lines.append(f"Latency (max): {max_rtt} ms")
            lines.append(f"Jitter (mdev): {mdev} ms")

        return "\n".join(lines)

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
        # Validate query parameter
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
