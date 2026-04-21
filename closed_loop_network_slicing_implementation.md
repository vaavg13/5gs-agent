# Closed-Loop Network Slicing Implementation Plan

## Organization First

Before implementation, impose one repo organization rule:

- Keep `examples/network_slicing/` intact as the baseline reference.
- Build the closed-loop and intent-centric work in `examples/intent_network_slicing/`.
- Prefer copying and renaming for clarity rather than partially migrating the baseline example.
- Move shared utilities into common modules only after the new example stabilizes.

This has been followed so far.

## Goal

Evolve this repo from "configure a slice and check SLA" into a closed-loop benchmark that can:

1. Diagnose root cause
2. Choose remediation
3. Apply change
4. Verify recovery
5. Penalize regressions, unsafe actions, and oscillation

The benchmark should measure more than final SLA compliance:

- time to recovery
- number of actions
- unsafe actions
- unnecessary restarts
- stability after recovery
- collateral impact on other UEs

## Current Status Snapshot

The new work now lives in `examples/intent_network_slicing/` and is no longer just a plan.

Implemented today:

- formal intent schema and dataset validation
- diagnosis-first workflow
- structured action journaling
- structured subscriber, SMF, and NSSF mutation tools
- multi-UE scenario foundation
- live three-slice scenario with differentiated premium / control / background behavior
- three working fault samples on that scenario
- benchmark-facing tool cleanup so the agent no longer gets the UPF answer directly

Still missing:

- scoring penalties for unsafe actions, restart storms, and oscillation
- time-to-recovery and stability-window scoring beyond final compliance
- a real policy-comparison harness
- additional scenarios beyond the current three-slice one
- stronger observability integration for offline analysis

## What Exists Now

### Repo structure

- `examples/network_slicing/` remains as the baseline example.
- `examples/intent_network_slicing/` is the active closed-loop benchmark prototype.
- `src/inspect_open5gs/sandbox.py` still provides the `open5gs` Inspect sandbox with serialized startup and stabilization delay.

### Intent-first task layer

Implemented under `examples/intent_network_slicing/`:

- `intents.py`
- `network_slicing.py`
- `dataset.yaml`
- `scorer.py`

Current state:

- dataset samples use formal `intent` objects
- intent validation happens at dataset load time
- scorer thresholds are derived from intent metadata
- task entrypoint is `three_slice_service_classes`

### Diagnosis and retrieval

Implemented:

- `diagnosis.py`
- `tools/retrieval.py`

Current state:

- there is a structured diagnosis tool
- UE, subscriber, config, NF state, connectivity, and filtered logs are available
- benchmark-facing log access is now service-aware
- the benchmark agent no longer has `get_upf_qos_state()`

### Structured actuation and audit

Implemented:

- `tools/action.py`
- `tools/subscriber.py`
- `action_journal.py`

Current state:

- structured actions exist for AMF, SMF, NSSF, subscriber mutation, UE registration, restart, and UPF service-class profile changes
- all state-changing tools journal actions in the Inspect sample store
- `exec_shell()` still exists as the unrestricted baseline actuator

### Scenario and runtime

Implemented:

- `scenarios/three_slice_service_classes/compose.yaml`
- differentiated subscriber / DNN / subnet configuration
- service-class shaping on the UPF
- persistent UERANSIM log capture

Current state:

- three active UEs:
  - `ue_premium`
  - `ue_control`
  - `ue_background`
- three differentiated service classes:
  - premium
  - control
  - background
- tunnel-forced measurements use `uesimtun0` rather than the Docker bridge

### Fault samples that already work

Current samples in `examples/intent_network_slicing/dataset.yaml`:

- `three_slice_service_classes_baseline`
- `three_slice_premium_service_demoted`
- `three_slice_premium_lossy`
- `three_slice_premium_subscriber_misrouted`

Validated outcomes:

- demoted premium service class produces real premium degradation with control stability
- lossy premium service class produces real premium packet loss with control stability
- subscriber misroute produces premium session failure while control remains healthy

## Phase Checklist

## Phase 0: Preserve The Baseline Example

- [x] Keep `examples/network_slicing/` intact
- [x] Create a separate `examples/intent_network_slicing/` line of work

## Phase 1: Make Intent First-Class

- [x] Add formal intent schema
- [x] Validate intents at dataset load time
- [x] Derive scorer expectations from intent
- [x] Support per-UE metrics in intent objectives

## Phase 2: Add Structured Diagnosis

- [x] Add diagnosis helper module
- [x] Add diagnosis tool to the agent
- [x] Introduce root-cause labels
- [x] Correlate subscriber, UE, NF, and UPF state

## Phase 3: Expand Safe Actuation

- [x] Add structured subscriber mutation
- [x] Add structured SMF mutation
- [x] Add structured NSSF mutation
- [x] Add UPF service-class profile actuation
- [x] Add action journaling
- [x] Keep `exec_shell()` as unrestricted baseline path

## Phase 4: Policy Comparison Harness

- [ ] Add explicit policy-family evaluation modes
- [ ] Compare unrestricted vs structured-only agents
- [ ] Record policy-family choice in scoring artifacts

Status:

- intentionally deferred

## Phase 5: Correct The Measurement Path

- [x] Ensure measurements traverse `uesimtun0`
- [x] Fix scorer path so it does not accidentally use the Docker bridge
- [x] Validate live throughput and latency against the differentiated scenario

## Phase 6: Add A Multi-UE Scenario Foundation

- [x] Add multiple active UEs
- [x] Add per-UE intent evaluation
- [x] Add differentiated slice / DNN / subnet profiles
- [x] Add collateral-damage-aware scenario design

Implemented as:

- `three_slice_service_classes`

## Phase 7: Build A Strong First Scenario

- [x] Rename the copied scenario to reflect its purpose
- [x] Implement live premium / control / background differentiation
- [x] Add at least three meaningful fault samples
- [x] Validate the faults with live Docker runs

## Phase 8: Make The Benchmark-Facing Agent Less Revealing

- [x] Remove direct UPF policy dump from the agent tool list
- [x] Improve service-aware log retrieval
- [x] Persist useful UERANSIM logs for diagnosis
- [x] Add safer subscriber lookup by UE service

## Phase 9: Turn Verification Into A Richer Loop

- [ ] Track time to first recovery
- [ ] Track time to sustained recovery
- [ ] Add stability-window scoring
- [ ] Distinguish eventual success from thrashing

Status:

- only final end-of-run compliance is scored today

## Phase 10: Upgrade The Scoring Model

- [ ] Penalize unnecessary restarts
- [ ] Penalize unsafe actions
- [ ] Penalize oscillation
- [ ] Penalize collateral damage explicitly
- [ ] Use action journal inside the score, not just for inspection

Status:

- action and restart counts are recorded
- they are not yet used as penalties

## Phase 11: Expand Fault Coverage

- [ ] Add more slicing faults on the current scenario
- [ ] Add non-slicing misconfiguration faults on the current scenario
- [ ] Add `two_slice_two_ue`
- [ ] Add a control-plane-oriented slicing scenario

## Phase 12: Improve Observability And Auditability

- [ ] Add Prometheus range-query support for the benchmark agent and scorer
- [ ] Export richer run artifacts for offline analysis
- [ ] Add action-to-metric timeline correlation
- [ ] Add NF health transition and restart telemetry

## Phase 13: Fix Repo Hygiene And Tests

- [ ] Add tests for new retrieval / actuation behavior
- [ ] Add tests for action journal consumption in the scorer
- [ ] Add tests for fault-injection helper scripts where practical
- [ ] Review stale tests that still reflect older repo assumptions

Current status:

- intent and diagnosis tests exist and pass
- broader closed-loop coverage is still missing

## Plan Corrections From The Original Draft

These are the places where implementation deliberately diverged from the earlier draft.

### 1. Work moved to `examples/intent_network_slicing/`

Original draft:

- many file references still assumed direct evolution of `examples/network_slicing/`

Current direction:

- all new benchmark work happens under `examples/intent_network_slicing/`
- the baseline example stays intact

### 2. Multi-UE came earlier and is already real

Original draft:

- multi-UE support appeared later in the roadmap

Current direction:

- multi-UE was required to make slice-remap and collateral-damage evaluation meaningful
- it is now implemented as the first real benchmark scenario

### 3. The main scenario is no longer `vr_gaming`

Original draft:

- roadmap examples were still anchored on `vr_gaming`

Current direction:

- the active scenario is `three_slice_service_classes`
- this better reflects the benchmark purpose

### 4. `get_upf_qos_state()` was too revealing

Original draft:

- richer observability included tools that directly exposed the policy state

Current direction:

- this tool was useful for debugging but too revealing for the benchmark-facing agent
- diagnosis should come from symptoms, logs, subscriber state, UE state, and measured outcomes

### 5. We are not adding many scenarios yet

Original draft:

- the roadmap risked expanding too many scenario families too early

Current direction:

- keep slicing scenarios to `2-3` purposeful variants
- reuse the same healthy scenario with different injected faults when possible
- add non-slicing faults as additional samples when a new topology is unnecessary

### 6. Policy harness remains deferred

Original draft:

- policy-family comparison was listed early as a major milestone

Current direction:

- first stabilize the scenario, fault set, tool surface, and scoring
- compare agent variants only after the benchmark is producing reliable traces

## What Needs To Be Built Next

Recommended next work, in order:

1. Use the action journal in the scorer.
   - add penalties for unsafe actions and unnecessary restarts
   - add explicit collateral-damage scoring

2. Add recovery timing and stability-window scoring.
   - first compliant timestamp
   - sustained compliant timestamp
   - post-recovery regression detection

3. Add a second slicing scenario.
   - `two_slice_two_ue`
   - simpler than the three-slice case
   - useful for faster debugging and early policy comparisons

4. Add non-slicing fault samples on the existing scenario.
   - registration / session recovery faults
   - NF restart-order faults
   - user-plane path failures

5. Split benchmark agent variants.
   - unrestricted baseline agent
   - structured-tools-only agent

## Proposed Minimal Next Milestone

The next milestone should not be "full production controller."

It should be:

1. Keep the current three working fault samples.
2. Add scoring penalties for action quality.
3. Add one simpler two-UE slicing scenario.
4. Add `2-3` non-slicing fault samples that reuse existing topology.
5. Compare unrestricted and structured agents on the same sample set.

If that milestone is complete, the repo will already be a credible closed-loop benchmark rather than just an SLA-checking task.

## Success Criteria For This Repo

This repo will have crossed from "slice config + SLA check" into a true closed-loop benchmark when it can answer all of the following from run artifacts:

- Did the agent identify the likely root cause before acting?
- Which remediation policy did it choose?
- Was the action safe and necessary?
- How long did recovery take?
- Did the system remain stable after recovery?
- Did recovery for the target UE cause unnecessary harm to other UEs?
- Did the agent overreact, oscillate, or restart unnecessarily?
- Which policy family performs best for which fault class?

Until those are measurable from run artifacts, the repo is still closer to an SLA verification benchmark than a full closed-loop operations benchmark.
