"""Open5GS sandbox environment for Inspect AI.

This package provides a Docker-based sandbox environment for running
Open5GS 5G Core evaluations with Inspect AI.

Example usage:
    # In a task definition
    @task
    def my_5g_task() -> Task:
        return Task(
            dataset=...,
            solver=[...],
            sandbox=("open5gs", "path/to/compose.yaml"),
        )

    # In tools, access containers via sandbox()
    from inspect_ai.util import sandbox

    result = await sandbox("amf").exec(["cat", "/opt/open5gs/etc/open5gs/amf.yaml"])
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Lazy imports to avoid loading heavy dependencies until needed
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Main sandbox environment
    "Open5GSSandboxEnvironment": ("sandbox", "Open5GSSandboxEnvironment"),
    # Observability
    "PrometheusClient": ("_observability", "PrometheusClient"),
    # Utilities
    "NF_CONFIGS": ("_util", "NF_CONFIGS"),
    "get_nf_config": ("_util", "get_nf_config"),
    "get_nf_config_path": ("_util", "get_nf_config_path"),
    "get_core_nf_names": ("_util", "get_core_nf_names"),
    "get_ran_names": ("_util", "get_ran_names"),
    "truncate_output": ("_util", "truncate_output"),
    # Config path constants
    "AMF_CONFIG_PATH": ("_util", "AMF_CONFIG_PATH"),
    "SMF_CONFIG_PATH": ("_util", "SMF_CONFIG_PATH"),
    "UPF_CONFIG_PATH": ("_util", "UPF_CONFIG_PATH"),
    "NRF_CONFIG_PATH": ("_util", "NRF_CONFIG_PATH"),
    "GNB_CONFIG_PATH": ("_util", "GNB_CONFIG_PATH"),
    "UE_CONFIG_PATH": ("_util", "UE_CONFIG_PATH"),
}

if TYPE_CHECKING:
    from inspect_open5gs._observability import PrometheusClient
    from inspect_open5gs._util import (
        AMF_CONFIG_PATH,
        GNB_CONFIG_PATH,
        NF_CONFIGS,
        NRF_CONFIG_PATH,
        SMF_CONFIG_PATH,
        UE_CONFIG_PATH,
        UPF_CONFIG_PATH,
        get_core_nf_names,
        get_nf_config,
        get_nf_config_path,
        get_ran_names,
        truncate_output,
    )
    from inspect_open5gs.sandbox import Open5GSSandboxEnvironment


def __getattr__(name: str) -> object:
    """Lazy load attributes on first access.

    This avoids importing heavy dependencies (aiohttp, etc.) until
    they're actually needed.
    """
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'inspect_open5gs' has no attribute '{name}'")

    module_name, attr_name = _LAZY_IMPORTS[name]
    from importlib import import_module

    module = import_module(f"inspect_open5gs.{module_name}")
    return getattr(module, attr_name)


def __dir__() -> list[str]:
    """Return list of available attributes for tab completion."""
    return list(_LAZY_IMPORTS.keys())


__all__ = list(_LAZY_IMPORTS.keys())
