"""Prometheus client for Open5GS observability integration.

Provides async access to Prometheus metrics exposed by Open5GS network functions.
AMF exposes metrics on port 9090, SMF on port 9091.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class PrometheusClient:
    """Async Prometheus query client.

    Provides methods to query Prometheus instant and range queries.
    Used by Open5GSSandboxEnvironment to expose metrics to agents.

    Example:
        >>> client = PrometheusClient("http://prometheus:9090")
        >>> result = await client.query("amf_n1_message_total")
        >>> print(result["data"]["result"])
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        """Initialize Prometheus client.

        Args:
            base_url: Prometheus server URL (e.g., "http://prometheus:9090")
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def query(self, promql: str) -> dict[str, Any]:
        """Execute a PromQL instant query.

        Args:
            promql: PromQL query string

        Returns:
            Prometheus API response with 'status' and 'data' keys

        Raises:
            aiohttp.ClientError: If request fails
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": promql},
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                logger.warning(f"Prometheus query failed: {e}")
                return {
                    "status": "error",
                    "errorType": "client_error",
                    "error": str(e),
                }

    async def query_range(
        self,
        promql: str,
        start: str,
        end: str,
        step: str = "15s",
    ) -> dict[str, Any]:
        """Execute a PromQL range query.

        Args:
            promql: PromQL query string
            start: Start time (RFC3339 or Unix timestamp)
            end: End time (RFC3339 or Unix timestamp)
            step: Query resolution step width (default: 15s)

        Returns:
            Prometheus API response with 'status' and 'data' keys

        Raises:
            aiohttp.ClientError: If request fails
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(
                    f"{self.base_url}/api/v1/query_range",
                    params={
                        "query": promql,
                        "start": start,
                        "end": end,
                        "step": step,
                    },
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                logger.warning(f"Prometheus range query failed: {e}")
                return {
                    "status": "error",
                    "errorType": "client_error",
                    "error": str(e),
                }

    async def get_metric_names(self) -> list[str]:
        """Get all available metric names from Prometheus.

        Returns:
            List of metric names, or empty list on error
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(
                    f"{self.base_url}/api/v1/label/__name__/values"
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data.get("data", [])
            except aiohttp.ClientError as e:
                logger.warning(f"Failed to get metric names: {e}")
                return []

    async def check_health(self) -> bool:
        """Check if Prometheus is healthy.

        Returns:
            True if Prometheus is healthy, False otherwise
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                async with session.get(f"{self.base_url}/-/healthy") as response:
                    return response.status == 200
            except aiohttp.ClientError:
                return False
