"""Tools for network slicing tasks.

This module exports all tools needed for the network slicing evaluation.
Tools are organized by category:
- retrieval: Read-only diagnostics (get_amf_config, get_logs, etc.)
- action: State-changing operations (modify_amf_config, restart_service, etc.)
- observability: Metrics and measurements (measure_throughput, query_prometheus, etc.)
"""

from .action import (
    exec_shell,
    modify_amf_config,
    restart_service,
    trigger_ue_registration,
)
from .observability import (
    measure_ue_latency,
    measure_ue_throughput,
    query_prometheus,
)
from .retrieval import (
    check_connectivity,
    get_amf_config,
    get_logs,
    get_network_config,
    get_nf_status,
    get_subscriber_info,
    get_ue_status,
)

__all__ = [
    # Retrieval
    "get_amf_config",
    "get_network_config",
    "get_subscriber_info",
    "get_nf_status",
    "get_ue_status",
    "get_logs",
    "check_connectivity",
    # Action
    "modify_amf_config",
    "restart_service",
    "trigger_ue_registration",
    "exec_shell",
    # Observability
    "measure_ue_throughput",
    "measure_ue_latency",
    "query_prometheus",
]
