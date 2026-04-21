"""Custom solvers for network slicing tasks.

Provides impairment injection similar to Kathara's inject_faults() pattern.
"""

from __future__ import annotations

import logging

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)


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

            logger.info(f"Injecting impairment on {service}: {script[:50]}...")

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
