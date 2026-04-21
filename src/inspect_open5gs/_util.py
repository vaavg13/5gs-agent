"""Utilities for Open5GS sandbox.

Contains network function configurations, path constants, and helper functions
used across the sandbox and examples.
"""

from __future__ import annotations

from typing import Any

# Maximum sizes for exec output and file transfers
MAX_EXEC_OUTPUT = 10 * 1024 * 1024  # 10MB
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Standard config paths inside containers
AMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/amf.yaml"
SMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/smf.yaml"
UPF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/upf.yaml"
NRF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/nrf.yaml"
GNB_CONFIG_PATH = "/etc/ueransim/gnb.yaml"
UE_CONFIG_PATH = "/etc/ueransim/ue.yaml"

# Network Function configurations (analogous to Kathara's IMAGE_CONFIGS)
# Metadata about each network function for tooling and health checks
NF_CONFIGS: dict[str, dict[str, Any]] = {
    "nrf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Network Repository Function - NF discovery and registration",
        "sbi_port": 7777,
        "config_path": NRF_CONFIG_PATH,
        "healthcheck": "curl -sf http://localhost:7777/nnrf-nfm/v1/nf-instances",
        "depends_on": ["mongo"],
    },
    "amf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Access and Mobility Management Function - UE registration",
        "sbi_port": 7777,
        "ngap_port": 38412,
        "metrics_port": 9090,
        "config_path": AMF_CONFIG_PATH,
        "healthcheck": "grep -q 38412 /proc/net/sctp/eps",
        "depends_on": ["nrf"],
    },
    "smf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Session Management Function - PDU session management",
        "sbi_port": 7777,
        "pfcp_port": 8805,
        "metrics_port": 9091,
        "config_path": SMF_CONFIG_PATH,
        "healthcheck": "ss -ulnp | grep -q 8805",
        "depends_on": ["nrf", "upf"],
    },
    "upf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "User Plane Function - Data plane forwarding",
        "pfcp_port": 8805,
        "config_path": UPF_CONFIG_PATH,
        "healthcheck": "ip link show ogstun",
        "depends_on": ["nrf"],
        "requires_privileged": True,
    },
    "ausf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Authentication Server Function",
        "sbi_port": 7777,
        "depends_on": ["nrf"],
    },
    "udm": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Unified Data Management",
        "sbi_port": 7777,
        "depends_on": ["nrf"],
    },
    "udr": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Unified Data Repository - Subscriber data",
        "sbi_port": 7777,
        "depends_on": ["nrf", "mongo"],
    },
    "pcf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Policy Control Function - QoS policies",
        "sbi_port": 7777,
        "depends_on": ["nrf", "mongo"],
    },
    "bsf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Binding Support Function",
        "sbi_port": 7777,
        "depends_on": ["nrf"],
    },
    "nssf": {
        "image": "openverso/open5gs:2.6.4",
        "description": "Network Slice Selection Function",
        "sbi_port": 7777,
        "depends_on": ["nrf"],
    },
    "gnb": {
        "image": "free5gc/ueransim:v4.2.0-aarch64",
        "description": "gNodeB - 5G base station",
        "config_path": GNB_CONFIG_PATH,
        "healthcheck": "pgrep -f nr-gnb",
        "depends_on": ["amf"],
    },
    "ue": {
        "image": "free5gc/ueransim:v4.2.0-aarch64",
        "description": "User Equipment - Mobile device",
        "config_path": UE_CONFIG_PATH,
        "healthcheck": "pgrep -f nr-ue",
        "depends_on": ["gnb"],
    },
    "mongo": {
        "image": "mongo:6.0",
        "description": "MongoDB - Subscriber database",
        "port": 27017,
        "healthcheck": "mongosh --eval \"db.adminCommand('ping')\"",
    },
}


def get_nf_config(nf_name: str) -> dict[str, Any] | None:
    """Get configuration for a network function.

    Args:
        nf_name: Network function name (e.g., "amf", "smf")

    Returns:
        Configuration dict or None if not found
    """
    return NF_CONFIGS.get(nf_name.lower())


def get_nf_config_path(nf_name: str) -> str | None:
    """Get the config file path for a network function.

    Args:
        nf_name: Network function name

    Returns:
        Config file path inside container, or None if not found
    """
    config = get_nf_config(nf_name)
    return config.get("config_path") if config else None


def get_core_nf_names() -> list[str]:
    """Get list of core network function names (excludes RAN and DB)."""
    return ["nrf", "amf", "smf", "upf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]


def get_ran_names() -> list[str]:
    """Get list of RAN component names."""
    return ["gnb", "ue"]


def truncate_output(output: str, max_size: int = MAX_EXEC_OUTPUT) -> str:
    """Truncate output to max_size bytes, keeping the end.

    When output exceeds max_size, truncates from the beginning and keeps
    the most recent output (end of string).

    Args:
        output: Output string to truncate
        max_size: Maximum size in bytes

    Returns:
        Truncated string (or original if within limit)
    """
    if len(output.encode("utf-8")) <= max_size:
        return output

    # Keep the end of the output (most recent)
    truncated = output.encode("utf-8")[-max_size:]

    # Find valid UTF-8 boundary
    for i in range(4):
        try:
            return truncated[i:].decode("utf-8")
        except UnicodeDecodeError:
            continue

    return truncated.decode("utf-8", errors="ignore")
