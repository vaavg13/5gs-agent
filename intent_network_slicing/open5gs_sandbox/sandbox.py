"""Open5GS sandbox environment for Inspect AI.

Extends DockerSandboxEnvironment to provide a clean abstraction over
the Open5GS 5G Core + UERANSIM stack with integrated observability.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.registry import sandboxenv
from typing_extensions import override

from intent_network_slicing.open5gs_sandbox._observability import PrometheusClient

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Concurrency Control
# -----------------------------------------------------------------------------

# Module-level semaphore to serialize container startup across concurrent samples.
# This prevents Docker daemon overwhelm when multiple 5G stacks start simultaneously.
# The semaphore is initialized lazily to ensure it's created in the correct event loop.
_startup_semaphore: asyncio.Semaphore | None = None
_startup_semaphore_lock = asyncio.Lock()

# Stabilization delay (seconds) after containers start before releasing semaphore.
# 5G core requires longer than typical apps due to NF registration with NRF.
STARTUP_STABILIZATION_DELAY = 30.0


async def _get_startup_semaphore() -> asyncio.Semaphore:
    """Get or create the startup semaphore (lazy initialization).

    The semaphore must be created within an async context to bind to the
    correct event loop. This function ensures thread-safe lazy creation.
    """
    global _startup_semaphore
    async with _startup_semaphore_lock:
        if _startup_semaphore is None:
            _startup_semaphore = asyncio.Semaphore(1)
        return _startup_semaphore


# -----------------------------------------------------------------------------
# Open5GS Sandbox Environment
# -----------------------------------------------------------------------------


@sandboxenv(name="open5gs")
class Open5GSSandboxEnvironment(DockerSandboxEnvironment):
    """Docker sandbox for Open5GS 5G Core with Prometheus observability.

    Extends DockerSandboxEnvironment to provide:

    1. **Conservative concurrency**: Defaults to 2 parallel stacks. Each 5G stack
       uses ~4GB memory with 11 NFs + UERANSIM + MongoDB.

    2. **Startup serialization**: Container startup is serialized via semaphore
       to prevent Docker daemon overwhelm from simultaneous `compose up` calls.

    3. **Stabilization delay**: After containers start, a 30s delay allows all
       NFs to register with NRF and establish inter-NF connections.

    4. **Prometheus integration**: `get_metrics()` method provides access to
       Open5GS metrics when the observability profile is enabled.

    Usage in dataset.yaml:
        sandbox: [open5gs, "three_slice_service_classes/compose.yaml"]

    The compose.yaml should include:
    - All Open5GS network functions with healthchecks
    - UERANSIM (gNB + UE)
    - Optional observability profile (Prometheus)

    Override concurrency via CLI:
        inspect eval --max-sandboxes 4  # If you have resources

    All DockerSandboxEnvironment features (exec, read_file, write_file, etc.)
    work unchanged.
    """

    # Prometheus client instance (lazy initialized)
    _prometheus_clients: dict[str, PrometheusClient] = {}

    @classmethod
    def default_concurrency(cls) -> int | None:
        """Return default concurrency of 2.

        Each Open5GS stack uses ~4GB memory. 2 is a safe default for most
        development machines with 16GB RAM. Override via --max-sandboxes
        for more powerful hardware.

        Returns:
            2 for parallel execution of 2 stacks
        """
        return 2

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        """Create sandbox with serialized startup to prevent Docker overwhelm.

        Even when Inspect schedules multiple samples in parallel (based on
        max_sandboxes), this method serializes the actual `compose up` calls.
        This prevents the Docker daemon from being overwhelmed by 100+ containers
        starting simultaneously.

        After containers start, a stabilization delay allows 5G NFs to:
        - Register with NRF (Network Repository Function)
        - Establish SBI (Service Based Interface) connections
        - Complete AMF/SMF/UPF signaling setup
        - Allow gNB to connect to AMF via NGAP
        """
        semaphore = await _get_startup_semaphore()

        async with semaphore:
            logger.info(f"Starting Open5GS stack for task '{task_name}'")

            # Parent class handles Docker Compose deployment
            # This triggers `docker compose up -d` and waits for healthchecks
            environments = await super().sample_init(task_name, config, metadata)

            # Wait for 5G stack stabilization
            # Docker Compose healthchecks ensure individual service readiness
            # This extra delay allows NF registration with NRF to complete
            logger.info(
                f"Waiting {STARTUP_STABILIZATION_DELAY}s for 5G core to stabilize"
            )
            await asyncio.sleep(STARTUP_STABILIZATION_DELAY)

        logger.info(f"Open5GS stack ready for task '{task_name}'")
        return environments

    async def get_metrics(self, query: str) -> dict[str, Any]:
        """Query Prometheus metrics from the observability stack.

        This is an Open5GS-specific extension to access Prometheus
        metrics when the observability profile is enabled.

        Args:
            query: PromQL query string (e.g., "amf_registered_subscribers")

        Returns:
            Prometheus query result as dict with 'status' and 'data' keys

        Raises:
            RuntimeError: If observability profile is not enabled

        Example:
            >>> result = await sandbox.get_metrics("amf_n1_message_total")
            >>> print(result["data"]["result"])
        """
        # Get project name from parent class
        project_name = getattr(self, "_project_name", None)
        if project_name is None:
            raise RuntimeError("Sandbox not initialized - _project_name not set")

        # Lazy initialize Prometheus client per project
        if project_name not in self._prometheus_clients:
            prometheus_url = f"http://{project_name}-prometheus:9090"
            self._prometheus_clients[project_name] = PrometheusClient(prometheus_url)

        return await self._prometheus_clients[project_name].query(query)

    async def get_metrics_range(
        self,
        query: str,
        start: str,
        end: str,
        step: str = "15s",
    ) -> dict[str, Any]:
        """Query Prometheus metrics over a time range.

        Args:
            query: PromQL query string
            start: Start time (RFC3339 or Unix timestamp)
            end: End time (RFC3339 or Unix timestamp)
            step: Query resolution step width (default: 15s)

        Returns:
            Prometheus range query result as dict
        """
        project_name = getattr(self, "_project_name", None)
        if project_name is None:
            raise RuntimeError("Sandbox not initialized - _project_name not set")

        if project_name not in self._prometheus_clients:
            prometheus_url = f"http://{project_name}-prometheus:9090"
            self._prometheus_clients[project_name] = PrometheusClient(prometheus_url)

        return await self._prometheus_clients[project_name].query_range(
            query, start, end, step
        )
