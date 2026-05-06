"""Inspect AI entry point registration for Open5GS sandbox.

This module is referenced in pyproject.toml [project.entry-points.inspect_ai]
to register the "open5gs" sandbox type with Inspect AI.
"""

from inspect_ai.util._sandbox.registry import sandboxenv


@sandboxenv(name="open5gs")
def open5gs():
    """Register the Open5GS sandbox environment with Inspect AI.

    This allows tasks to use:
        sandbox=("open5gs", "path/to/compose.yaml")

    The sandbox extends DockerSandboxEnvironment with:
    - Serialized startup to prevent Docker overwhelm
    - 30s stabilization delay for 5G NF registration
    - Prometheus metrics access via get_metrics()
    """
    from intent_network_slicing.open5gs_sandbox.sandbox import Open5GSSandboxEnvironment

    return Open5GSSandboxEnvironment
