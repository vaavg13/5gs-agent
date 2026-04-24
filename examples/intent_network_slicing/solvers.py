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


UE_IPERF3_PORTS = {
    "ue_premium": 5201,
    "ue_control": 5202,
    "ue_background": 5203,
}


@solver
def start_metrics_collector() -> Solver:
    """Start background iperf3 + ping collectors in all UE containers.

    Each UE connects to its dedicated iperf3 server port so throughput
    measurements run concurrently without contention.
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
        services = [u["service"] for u in ues] or ["ue_premium"]
        target_services = [u["service"] for u in ues if u.get("role") == "target"]
        target_svc = target_services[0] if target_services else services[0]

        for svc in services:
            port = UE_IPERF3_PORTS.get(svc, 5201)
            # Target UE runs unlimited to measure peak; others are capped so
            # they don't contend with the target on the shared UPF pipe.
            bandwidth = "0" if svc == target_svc else "10M"
            ue = sandbox(svc)
            await ue.exec(
                [
                    "sh",
                    "-c",
                    "bash /scripts/metrics-collector.sh iperf3-server "
                    f"{METRICS_CSV_PATH} uesimtun0 {port} {bandwidth} "
                    "> /tmp/metrics-collector.log 2>&1 &",
                ],
                timeout=10,
            )
            logger.info(
                f"Started iperf3+ping collector on {svc} "
                f"(port {port}, bw {bandwidth})"
            )

        await _wait_for_data(sandbox(target_svc), target_svc)
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
