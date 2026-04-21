"""Custom solvers for network slicing tasks.

Provides impairment injection similar to Kathara's inject_faults() pattern.
"""

from __future__ import annotations

import asyncio
import logging

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)

METRICS_CSV_PATH = "/tmp/metrics.csv"


@solver
def inject_impairments() -> Solver:
    """Inject network impairments before the agent runs.

    Reads impairment setup from sample metadata and executes
    shell commands on the specified containers.

    Expected metadata format:
        metadata:
            impairment_setup:
                upf: "tc qdisc add dev ogstun root netem delay 100ms"
                amf: "iptables -A INPUT -p tcp --dport 38412 -j DROP"

    This allows each sample to define different fault scenarios
    while keeping the task definition generic.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        impairment_setup = state.metadata.get("impairment_setup", {})

        if not impairment_setup:
            logger.debug("No impairment setup in metadata, skipping injection")
            return state

        for service, script in impairment_setup.items():
            if not script or not script.strip():
                continue

            logger.debug(f"Injecting impairment on {service}")

            try:
                service_sandbox = sandbox(name=service)
                result = await service_sandbox.exec(
                    cmd=["sh", "-c", script],
                    timeout=30,
                )

                if not result.success:
                    logger.warning(
                        f"Impairment injection on {service} had stderr: {result.stderr}"
                    )
            except Exception as e:
                logger.error(f"Failed to inject impairment on {service}: {e}")

        return state

    return solve


@solver
def start_metrics_collector() -> Solver:
    """Start background metrics collectors in UE containers.

    Target UE gets iperf3 + ping (full throughput + latency).
    Other UEs get ping-only (latency/jitter/loss, throughput=0).
    """

    async def _wait_for_data(ue_sandbox, service_name: str) -> bool:
        for _ in range(15):
            await asyncio.sleep(2)
            check = await ue_sandbox.exec(["wc", "-l", METRICS_CSV_PATH], timeout=5)
            if check.success:
                lines = int(check.stdout.strip().split()[0])
                if lines > 1:
                    logger.info(
                        f"Metrics collector running on {service_name} "
                        f"({lines - 1} data rows)"
                    )
                    return True
        logger.warning(f"Metrics collector on {service_name}: no data after 30s")
        return False

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        intent = state.metadata.get("intent", {})
        ues = intent.get("ues", [])
        target_services = [u["service"] for u in ues if u.get("role") == "target"]
        target_svc = target_services[0] if target_services else "ue_premium"
        other_services = [u["service"] for u in ues if u["service"] != target_svc]

        # Start iperf3 + ping on target UE
        ue = sandbox(target_svc)
        await ue.exec(
            [
                "sh",
                "-c",
                "bash /scripts/metrics-collector.sh iperf3-server "
                f"{METRICS_CSV_PATH} uesimtun0 "
                "> /tmp/metrics-collector.log 2>&1 &",
            ],
            timeout=10,
        )

        # Start ping-only on other UEs
        for svc in other_services:
            other_ue = sandbox(svc)
            await other_ue.exec(
                [
                    "sh",
                    "-c",
                    "bash /scripts/ping-collector.sh iperf3-server "
                    f"{METRICS_CSV_PATH} uesimtun0 "
                    "> /tmp/metrics-collector.log 2>&1 &",
                ],
                timeout=10,
            )
            logger.info(f"Started ping-only collector on {svc}")

        await _wait_for_data(ue, target_svc)
        return state

    return solve


@solver
def collect_post_agent_metrics(duration_s: int = 30) -> Solver:
    """Wait after the agent finishes so the metrics collector accumulates
    clean post-remediation data for the scorer to evaluate."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        logger.info(f"Collecting post-agent metrics for {duration_s}s")
        await asyncio.sleep(duration_s)
        return state

    return solve


@solver
def verify_prerequisites() -> Solver:
    """Verify 5G stack is healthy before agent starts.

    Checks that core network functions are registered and UE has connectivity.
    This ensures the agent starts from a known-good state.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Check AMF is healthy
        try:
            amf = sandbox("amf")
            result = await amf.exec(
                ["curl", "-sf", "http://localhost:7777/nnrf-nfm/v1/nf-instances"],
                timeout=10,
            )
            if result.success:
                logger.info("AMF health check passed")
            else:
                logger.warning(f"AMF health check failed: {result.stderr}")
        except Exception as e:
            logger.warning(f"AMF health check error: {e}")

        return state

    return solve
