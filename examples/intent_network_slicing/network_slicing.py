"""Network slicing task for Open5GS sandbox.

Evaluates AI agents on intent-driven diagnosis and recovery for 5G slices.
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

from intents import (
    IntentValidationError,
    build_expected_metrics_from_intent,
    format_intent_summary,
    validate_intent,
)
from scorer import sla_compliance_scorer
from solvers import inject_impairments, start_metrics_collector
from tools.action import (
    apply_upf_qos_config,
    exec_shell,
    get_upf_qos_config,
    modify_amf_config,
    restart_service,
    sleep_seconds,
    trigger_ue_registration,
    upsert_nssf_slice,
    upsert_smf_slice,
)
from tools.observability import (
    measure_ue_latency,
    measure_ue_throughput,
    query_prometheus,
)
from tools.retrieval import (
    check_connectivity,
    diagnose_network_issue,
    get_action_journal,
    get_amf_config,
    get_logs,
    get_network_config,
    get_nf_status,
    get_subscriber_info,
    get_ue_status,
)
from tools.subscriber import update_subscriber_slice

_SCENARIOS_DIR = _TASK_DIR / "scenarios"

SYSTEM_PROMPT = """You are a 5G network slice engineer specializing in Open5GS and UERANSIM.

## Your Task
Satisfy the formal service intent while minimizing unnecessary changes.

## Available Tools

### Diagnostics (Read-Only)
- diagnose_network_issue: Collect raw diagnostic data from network components
- get_action_journal: Inspect the action history recorded by state-changing tools
- get_amf_config: Read AMF configuration (GUAMI, TAI, slices)
- get_network_config: Read SMF/UPF/gNB configuration
- get_upf_qos_config: Read current UPF traffic-shaping parameters
- get_subscriber_info: Query subscriber database by IMSI or UE service
- get_nf_status: Check NF registration with NRF
- get_ue_status: Check UE registration and PDU session
- get_logs: Read service-aware Open5GS or UERANSIM logs with optional filtering
- check_connectivity: Test UE connectivity

### Configuration (State-Changing)
- modify_amf_config: Update AMF YAML configuration
- apply_upf_qos_config: Write and apply UPF traffic-shaping configuration
- upsert_smf_slice: Create or update an SMF slice to DNN mapping
- upsert_nssf_slice: Create or update an NSSF slice selection entry
- update_subscriber_slice: Update subscriber slice and DNN in MongoDB
- restart_service: Restart network functions after config changes
- trigger_ue_registration: Re-register UE after changes
- sleep_seconds: Pause to let changes settle before re-measuring
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
- This scenario typically exposes `ue_premium`, `ue_control`, and `ue_background`
- Config changes require service restarts (Open5GS has no hot-reload)
- S-NSSAI format: `{sst: <int>, sd: "<hex>"}` (e.g., `{sst: 1, sd: "000002"}`)
- The iperf3 server is reachable at hostname 'iperf3-server'
- Start with diagnosis before taking state-changing actions
- Verify each step before proceeding

## When to Stop
You control when to exit. Your final measurement window is what gets scored,
so the last measurements before you stop should reflect a stable, healthy state.

- After applying a change, use `sleep_seconds` (typically 10–20s) to let
  traffic shaping rules settle and the rolling measurement averages catch up.
- Then re-measure with `measure_ue_throughput` and `measure_ue_latency`.
- Exit only once all SLA hard objectives are satisfied in the current window
  and the readings look stable (not still transitioning).
- Measurements are rolling averages over recent seconds — fresh changes
  need time to dominate the window.

Work methodically. Use diagnostic tools to understand current state before making changes.
"""


def _build_sample_input(record: dict, prompt_template: str) -> str:
    """Build agent prompt text from template, intent, and sample-specific instructions."""
    parts = []
    if prompt_template.strip():
        parts.append(prompt_template.strip())

    intent = record.get("intent")
    if intent:
        parts.append("Formal intent:\n" + format_intent_summary(intent))

    sample_input = record.get("input", "")
    if sample_input.strip():
        parts.append(sample_input.strip())

    return "\n\n".join(parts)


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
        # Handle sandbox path resolution
        sandbox_config = record.get(
            "sandbox",
            ["open5gs", "three_slice_service_classes/compose.yaml"],
        )
        if isinstance(sandbox_config, list):
            sandbox_config = _resolve_compose_path(sandbox_config)

        # Build metadata including intent and impairment setup
        metadata = record.get("metadata", {}).copy()
        intent = record.get("intent")
        if intent:
            try:
                normalized_intent = validate_intent(intent)
            except IntentValidationError as exc:
                sample_id = record.get("id", "<unknown>")
                raise ValueError(f"Invalid intent in sample '{sample_id}': {exc}") from exc
            metadata["intent"] = normalized_intent
            metadata.setdefault(
                "expected_metrics",
                build_expected_metrics_from_intent(normalized_intent),
            )

        if record.get("setup"):
            metadata["impairment_setup"] = record["setup"]

        sample_input = _build_sample_input(record, prompt_template)

        samples.append(
            Sample(
                id=record.get("id"),
                input=sample_input,
                target=record.get("target", ""),
                sandbox=sandbox_config,
                metadata=metadata,
            )
        )

    return MemoryDataset(samples=samples, name="intent_network_slicing")


def _intent_network_task() -> Task:
    """Intent-driven slice recovery task.

    Evaluates AI agent ability to diagnose faults against a formal intent,
    then recover service with minimal, justified changes.

    The agent must:
    1. Diagnose current network state and likely root cause
    2. Apply targeted remediation
    3. Verify the service intent is satisfied

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
                    diagnose_network_issue(),
                    get_action_journal(),
                    get_amf_config(),
                    get_network_config(),
                    get_upf_qos_config(),
                    get_subscriber_info(),
                    get_nf_status(),
                    get_ue_status(),
                    get_logs(),
                    check_connectivity(),
                    # Configuration
                    modify_amf_config(),
                    apply_upf_qos_config(),
                    upsert_smf_slice(),
                    upsert_nssf_slice(),
                    update_subscriber_slice(),
                    restart_service(),
                    trigger_ue_registration(),
                    sleep_seconds(),
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


@task
def three_slice_service_classes() -> Task:
    """Three-slice service-class recovery task."""
    return _intent_network_task()


@task
def vr_gaming_intent_slice() -> Task:
    """Backward-compatible alias for older task references."""
    return _intent_network_task()
