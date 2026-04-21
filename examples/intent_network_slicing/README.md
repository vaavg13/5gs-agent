# Intent Network Slicing Evaluation

This example focuses on a three-slice Open5GS scenario with distinct service classes:

- `ue_premium`: target subscriber that should receive premium throughput and low latency
- `ue_control`: protected subscriber that should remain stable during remediation
- `ue_background`: background subscriber that can absorb contention or misapplied prioritization

## Active Scenario

The active scenario lives under [three_slice_service_classes](/data/avgerinos/projects/5gs-sandbox/examples/intent_network_slicing/scenarios/three_slice_service_classes).

A scenario is the healthy environment or topology:
- number of UEs
- slice layout
- subscriber classes
- DNN/subnet structure
- intended service relationships

A fault is then injected on top of that healthy scenario through the dataset `setup` field.
This means many experiments can reuse the same scenario and differ only by the injected fault.

Healthy profile:
- `premium`: high throughput, low delay
- `control`: moderate throughput, moderate delay
- `background`: low throughput, high delay

Current implemented faults:
- premium is demoted to the background class while background is promoted
- premium keeps its premium class but suffers packet loss on the UPF
- premium subscriber metadata is misrouted to the background slice/DNN

The fault is applied on the UPF with `tc` shaping on `ogstun`, so traffic still stays inside the 5G user plane and can be measured through `uesimtun0`.

### Fault Types For `three_slice_service_classes`

Already implemented:
- `service_class_demoted`: premium traffic is shaped like background traffic
- `lossy_premium`: premium keeps its slice but suffers packet loss on the UPF
- `subscriber_misrouted`: premium subscriber profile is moved to the wrong slice/DNN and loses its intended session

Natural next faults for the same scenario:
- `control_plane_slice_mismatch`: SMF or NSSF maps the premium slice to the wrong DNN
- `partial_remediation_regression`: premium is restored but control or background is harmed
- `restart_storm`: repeated NF or UE restarts recover service but are operationally unsafe
- `background_overpromotion`: background traffic unfairly captures premium treatment without fully disconnecting premium

## Dataset Variants

Current samples in [dataset.yaml](/data/avgerinos/projects/5gs-sandbox/examples/intent_network_slicing/dataset.yaml):

- `three_slice_service_classes_baseline`: verify the healthy three-UE layout
- `three_slice_premium_service_demoted`: diagnose and recover the demoted premium service class
- `three_slice_premium_lossy`: diagnose and recover premium packet loss on the UPF
- `three_slice_premium_subscriber_misrouted`: restore the premium subscriber mapping after a control-plane profile error

## Task Entry Point

Use [network_slicing.py](/data/avgerinos/projects/5gs-sandbox/examples/intent_network_slicing/network_slicing.py):

```bash
inspect eval network_slicing.py@three_slice_service_classes --model openai/gpt-4o
```

Compatibility alias:

```bash
inspect eval network_slicing.py@vr_gaming_intent_slice --model openai/gpt-4o
```

## Important Tools

Diagnostics:
- `diagnose_network_issue()`
- `get_logs()`
- `get_subscriber_info()`
- `get_ue_status()`
- `measure_ue_throughput()`
- `measure_ue_latency()`

Remediation:
- `apply_service_class_profile("healthy" | "demoted" | "lossy_premium")`
- `update_subscriber_slice(...)`
- `upsert_smf_slice(...)`
- `upsert_nssf_slice(...)`
- `restart_service(...)`
- `trigger_ue_registration(...)`
- `exec_shell(...)` as the unconstrained baseline actuator

## Live Behavior

With the current shaping profiles, the scenario produces a clear contrast:

- healthy premium: about `725 Mbit/s`, `~2.7 ms`
- healthy control: about `526 Mbit/s`, `~8.8 ms`
- healthy background: about `43 Mbit/s`, `~36 ms`

After loading the demoted profile:

- premium falls to about `36 Mbit/s`, `~36 ms`
- control stays near `338 Mbit/s`, `~8.6 ms`
- background improves to about `694 Mbit/s`, `~2.7 ms`

After loading the lossy premium profile:

- premium stays low-latency but shows about `15%` packet loss
- control remains at `0%` packet loss and `~8.6 ms`

After misrouting the premium subscriber:

- `ue_premium` loses `uesimtun0`
- UE logs report `DNN_NOT_SUPPORTED_OR_NOT_SUBSCRIBED`
- `ue_control` remains healthy

Those outcomes make the scenario suitable for target-recovery, collateral-impact, and mixed control-plane/user-plane experiments.

## Suggested Scenario Roadmap

These are the most useful next scenarios to place under [scenarios](/data/avgerinos/projects/5gs-sandbox/examples/intent_network_slicing/scenarios). The idea is to keep the set small and intentional rather than adding many overlapping variants.

### Slicing Scenario Ladder

Keep slicing scenarios to `2-3` concrete variants that increase in difficulty and introduce new evaluation value.

### `two_slice_two_ue`

Purpose:
- simplest slicing benchmark
- easier version of `three_slice_service_classes`
- one target UE and one competing UE

Why it is useful:
- easier to debug than three slices
- good first benchmark for subscriber/profile mistakes and unfair promotion
- establishes whether the agent can restore the target slice without extra complexity

Likely fault types:
- target subscriber mapped to competitor slice
- competitor promoted into target slice treatment
- wrong DNN for one of the two slices
- simple UPF class demotion on the target slice

### `three_slice_service_classes`

Purpose:
- current main slicing scenario
- one target UE, one protected UE, one background UE

Why it is useful:
- introduces collateral-damage detection
- supports privileged recovery without harming the protected UE
- supports both user-plane and subscriber-profile faults

Likely fault types:
- service-class demotion
- lossy premium path
- subscriber misroute
- SMF or NSSF slice-to-DNN mismatch
- partial remediation that restores premium but harms control

### `three_slice_control_plane_mismatch`

Purpose:
- separate the control-plane slice-selection problem from pure UPF shaping

Why it is useful:
- tests whether the agent can reason about subscriber, SMF, and NSSF consistency
- forces restart and re-registration reasoning instead of simple policy reapply

Likely fault types:
- subscriber points to wrong slice or DNN
- SMF slice maps to wrong DNN/subnet
- NSSF entry missing or incorrect
- remediation is logically correct but incomplete because required restart or re-registration is skipped

## Non-Slicing Scenarios To Add

These broaden the benchmark beyond slicing without requiring application-level traffic generation.
They do not always require a new scenario. If the healthy environment already supports them, they can simply be added as new fault samples on top of an existing scenario such as `three_slice_service_classes`.

### `registration_and_session_recovery`

Purpose:
- recover service when the problem is attachment or session setup, not slice priority

Likely fault types:
- wrong UE subscriber credentials or stale subscriber state
- PDU session establishment failure
- DNN not supported or not subscribed
- UE needs re-registration after control-plane repair

Can reuse existing scenario:
- yes, often

### `nf_restart_order_and_dependency`

Purpose:
- test whether the agent can recover the stack safely when NF ordering matters

Likely fault types:
- SMF restarted without restoring UPF or NRF dependencies
- AMF healthy by process but not operationally useful
- repeated restarts create oscillation instead of recovery
- service is restored only when restart sequence is correct

Can reuse existing scenario:
- yes

### `user_plane_path_failure`

Purpose:
- focus on forwarding/NAT/path issues rather than slice assignment

Likely fault types:
- missing or broken `ogstun` setup
- NAT or forwarding rules absent on the UPF
- PFCP relationship intact but data plane unusable
- connectivity restored by UPF or path repair rather than slice remap

Can reuse existing scenario:
- yes
