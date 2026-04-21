"""Network slicing task for Open5GS sandbox.

Evaluates AI agents on configuring 5G network slices with SLA requirements.
This example demonstrates the Inspect-native patterns for 5G evaluations.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add examples directory to path for direct execution via `inspect eval`
_TASK_DIR = Path(__file__).parent
if str(_TASK_DIR) not in sys.path:
    sys.path.insert(0, str(_TASK_DIR))

import yaml
from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import system_message

from scorer import sla_compliance_scorer
from solvers import inject_impairments, start_metrics_collector
from tools.action import (
    exec_shell,
    modify_amf_config,
    restart_service,
    trigger_ue_registration,
)
from tools.observability import (
    measure_ue_latency,
    measure_ue_throughput,
    query_prometheus,
)
from tools.retrieval import (
    check_connectivity,
    get_amf_config,
    get_logs,
    get_network_config,
    get_nf_status,
    get_subscriber_info,
    get_ue_status,
)

_SCENARIOS_DIR = _TASK_DIR / "scenarios"

SYSTEM_PROMPT = """You are a 5G network slice engineer specializing in Open5GS and UERANSIM.

## Your Task
Configure a network slice to meet the specified SLA requirements.

## Available Tools

### Diagnostics (Read-Only)
- get_amf_config: Read AMF configuration (GUAMI, TAI, slices)
- get_network_config: Read SMF/UPF/gNB configuration
- get_subscriber_info: Query subscriber database
- get_nf_status: Check NF registration with NRF
- get_ue_status: Check UE registration and PDU session
- get_logs: Read container logs for debugging
- check_connectivity: Test UE connectivity

### Configuration (State-Changing)
- modify_amf_config: Update AMF YAML configuration
- restart_service: Restart network functions after config changes
- trigger_ue_registration: Re-register UE after changes
- exec_shell: Execute shell commands for advanced operations

### Measurement (from continuous monitoring stream)
- measure_ue_throughput: Read throughput from the live iperf3 monitoring stream
- measure_ue_latency: Read latency/jitter/loss from the live ping monitoring stream
- query_prometheus: Query 5G metrics

## Network Architecture
```
┌──────┐    NGAP    ┌─────┐   SBI   ┌─────┐   PFCP   ┌─────┐
│ gNB  │◄──────────►│ AMF │◄───────►│ SMF │◄────────►│ UPF │
└──────┘            └─────┘         └─────┘          └─────┘
   │                                                     │
   │ RRC/NAS                                            │ GTP-U
   │                                                     │
┌──────┐                                          ┌──────────┐
│  UE  │ uesimtun0 (10.46.x.x)                   │ iperf3   │
└──────┘◄─────────────────────────────────────────►│ server   │
                   Data Plane                      └──────────┘
```

## Important Notes
- Config changes require service restarts (Open5GS has no hot-reload)
- S-NSSAI format: `{sst: <int>, sd: "<hex>"}` (e.g., `{sst: 1, sd: "000002"}`)
- The iperf3 server is reachable at hostname 'iperf3-server'
- Verify each step before proceeding

Work methodically. Use diagnostic tools to understand current state before making changes.
"""


def _resolve_compose_path(sandbox_config: list | tuple) -> tuple:
    """Resolve sandbox config to absolute compose path."""
    if len(sandbox_config) < 2:
        return tuple(sandbox_config)

    sandbox_type, config_path = sandbox_config[0], sandbox_config[1]
    config_path = Path(config_path)

    if not config_path.is_absolute():
        config_path = _SCENARIOS_DIR / config_path

    if config_path.is_dir():
        config_path = config_path / "compose.yaml"

    return (sandbox_type, str(config_path.resolve()))


def load_dataset(yaml_path: Path | None = None) -> MemoryDataset:
    """Load dataset from YAML file.

    Args:
        yaml_path: Path to dataset YAML. Defaults to dataset.yaml in task dir.

    Returns:
        MemoryDataset with samples.
    """
    yaml_path = yaml_path or _TASK_DIR / "dataset.yaml"

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    prompt_template = data.get("prompt_template", "")

    samples = []
    for record in data.get("samples", []):
        # Merge prompt template with sample input
        sample_input = record.get("input", prompt_template)

        # Handle sandbox path resolution
        sandbox_config = record.get("sandbox", ["open5gs", "vr_gaming"])
        if isinstance(sandbox_config, list):
            sandbox_config = _resolve_compose_path(sandbox_config)

        # Build metadata including impairment setup
        metadata = record.get("metadata", {}).copy()
        if record.get("setup"):
            metadata["impairment_setup"] = record["setup"]

        samples.append(
            Sample(
                id=record.get("id"),
                input=sample_input,
                target=record.get("target", ""),
                sandbox=sandbox_config,
                metadata=metadata,
            )
        )

    return MemoryDataset(samples=samples, name="network_slicing")


@task
def vr_gaming_slice() -> Task:
    """VR Gaming eMBB Network Slice Configuration Task.

    Evaluates AI agent ability to configure a high-performance eMBB slice
    for VR gaming with strict SLA requirements.

    The agent must:
    1. Diagnose current network configuration
    2. Configure slice settings (S-NSSAI, QoS)
    3. Apply changes and restart services
    4. Verify connectivity and performance

    Returns:
        Task with dataset, solver, and scorer.
    """
    return Task(
        dataset=load_dataset(),
        solver=[
            inject_impairments(),  # Inject faults before agent runs
            start_metrics_collector(),  # Start continuous monitoring
            system_message(SYSTEM_PROMPT),
            react(
                tools=[
                    # Diagnostics
                    get_amf_config(),
                    get_network_config(),
                    get_subscriber_info(),
                    get_nf_status(),
                    get_ue_status(),
                    get_logs(),
                    check_connectivity(),
                    # Configuration
                    modify_amf_config(),
                    restart_service(),
                    trigger_ue_registration(),
                    exec_shell(),
                    # Measurement
                    measure_ue_throughput(),
                    measure_ue_latency(),
                    query_prometheus(),
                ],
            ),
        ],
        scorer=sla_compliance_scorer(),
        message_limit=30,
    )
