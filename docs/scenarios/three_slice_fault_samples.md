# Three-Slice Fault Samples — Expansion Plan

Plan for expanding `three_slice_service_classes` from 4 to 9 fault samples,
increasing diagnostic coverage across UPF, MongoDB, AMF, and SMF subsystems.

Context: Phase 11 of [roadmap.md](../roadmap.md) calls for "more slicing faults"
and "non-slicing misconfiguration faults" reusing the existing healthy scenario.

## Current Samples (4)

| Sample ID | Subsystem | Fault |
|---|---|---|
| `three_slice_service_classes_baseline` | — | Healthy (no impairment) |
| `three_slice_premium_service_demoted` | UPF tc | Premium class rates/delays swapped with background |
| `three_slice_premium_lossy` | UPF tc | 8% netem loss on premium class |
| `three_slice_premium_subscriber_misrouted` | MongoDB | Subscriber's SST/SD changed to background |

Diagnostic coverage so far: **UPF tc rules** (x2) and **subscriber slice fields** (x1).

## New Samples (5)

Each sample exercises a distinct diagnostic path. They all reuse the healthy
three-slice scenario and only differ in the `setup:` block.

### 5. `premium_ambr_throttled`

**Subsystem:** MongoDB subscriber AMBR fields
**Symptom:** Latency/jitter/loss OK, but premium UE throughput capped at ~1 Mbps
**Impairment:** Set subscriber AMBR to `{value: 1, unit: 3}` (1 Mbps) for both
uplink and downlink
**Correct fix:** Update AMBR back to 10 Gbit (`{value: 10, unit: 4}`) via
`update_subscriber_slice` or direct mongo update, then trigger UE re-registration
so the new AMBR takes effect
**What it tests:** Agent must read the subscriber record's AMBR fields (not just
slice SST/SD) and understand that AMBR is the session-level bandwidth cap

### 6. `premium_amf_slice_missing`

**Subsystem:** AMF `plmn_support` configuration
**Symptom:** `ue_premium` fails NAS registration ("Requested NSSAI not allowed")
or falls back to default slice; premium PDU session fails
**Impairment:** Remove the `{sst:1, sd:000002}` entry from AMF's
`plmn_support[0].s_nssai` list in `amf.yaml`
**Correct fix:** `modify_amf_config` to re-add the slice entry, then
`restart_service('amf')` (Open5GS has no hot-reload), then `trigger_ue_registration`
**What it tests:** Agent must read AMF config, identify a missing slice, and
apply a config change that needs a service restart

### 7. `premium_smf_dnn_missing`

**Subsystem:** SMF `info` list (slice → DNN mapping)
**Symptom:** UE registers successfully but premium PDU session fails; control
and background sessions work
**Impairment:** Remove the premium DNN entry from SMF's `info` list
**Correct fix:** `upsert_smf_slice(sst=1, sd="000002", dnn="premium", subnet="10.46.20.0/24")`
then `restart_service('smf')`
**What it tests:** Agent must distinguish registration success from session-setup
failure, inspect SMF config, and use the structured SMF tool

### 8. `premium_jitter_heavy`

**Subsystem:** UPF tc netem parameters (non-loss, non-rate)
**Symptom:** Throughput OK, latency avg OK, but **jitter fails** (SLA ≤ 5ms violated)
**Impairment:** Apply a service-class config with `premium_delay_ms: 2` but add
netem jitter — requires extending the QoS script to support a jitter parameter,
OR using a direct `tc qdisc change` command with `delay 2ms 20ms distribution normal`
**Correct fix:** `apply_upf_qos_config` without the jitter, restoring base delay
**What it tests:** Agent distinguishes latency from jitter symptoms and reads
the netem qdisc output carefully (jitter is a secondary netem parameter)

### 9. `premium_combined_qos_and_subscriber`

**Subsystem:** Multi-fault (UPF tc + MongoDB subscriber)
**Symptom:** Poor throughput **and** wrong slice mapping; fixing one alone
doesn't satisfy the SLA
**Impairment:** Apply the demoted QoS AND change the subscriber AMBR to 1 Mbps
**Correct fix:** Both `apply_upf_qos_config` (restore rates) AND
`update_subscriber_slice` (restore AMBR) + `trigger_ue_registration`
**What it tests:** Iterative diagnosis — the agent must notice that after
fixing the first issue, SLAs are still violated, and continue searching

## Infrastructure Needs

### New setup scripts

- `scripts/set-subscriber-ambr.sh IMSI DL_VALUE UL_VALUE` — helper for AMBR
  mutation (similar to existing `set-subscriber-profile.sh`)
- `scripts/remove-amf-slice.sh SST SD` — strip a slice entry from `amf.yaml`
  (uses `yq` or a small Python helper)
- `scripts/remove-smf-dnn.sh DNN` — strip a DNN entry from SMF `info`

### Script tweaks

- `apply-service-class-qos.sh` — add optional jitter parameter
  (`<class>_jitter_ms`) so the jitter scenario can be injected via the same
  path as other UPF faults

### Scorer considerations

- None — existing intent objectives (`max_jitter_ms`, `uplink_throughput_mbps`,
  etc.) already cover all new symptoms

## Intent Objectives Tuning

All new samples reuse the baseline intent with the same hard objectives. The
`recovery_deadline_s` and `max_restarts` may need bumping for:

- `premium_amf_slice_missing` / `premium_smf_dnn_missing` — require a restart,
  so bump `max_restarts` from 0 to 1
- `premium_combined_qos_and_subscriber` — more steps; bump `recovery_deadline_s`
  to 180 and `max_restarts` to 2

## Verification Approach

For each new sample:

1. **Impairment isolation test** — run the sample with the agent effectively
   disabled (single `get_ue_status` call then exit) to confirm the impairment
   actually violates the SLA
2. **Happy-path test** — run with a capable model (gpt-5.4) and confirm the
   expected fix tool path produces a PASS score
3. **Behavioral variance check** — run 3 seeds to confirm the scenario is not
   trivially easy (score should vary)

## Implementation Order

Recommended sequence:

1. `premium_ambr_throttled` — easiest, only needs one setup script tweak
2. `premium_smf_dnn_missing` — exercises existing `upsert_smf_slice` tool
3. `premium_amf_slice_missing` — exercises `modify_amf_config`
4. `premium_jitter_heavy` — requires QoS script extension
5. `premium_combined_qos_and_subscriber` — composite, do last once the
   constituent faults are validated

## Deferred (not in this expansion)

From the Phase 11 roadmap, these remain deferred:

- `two_slice_two_ue` — new scenario family, requires new compose / subscribers
- Dedicated control-plane scenario — revisit after Phase 11's non-slicing
  faults land
- NRF degradation, IP pool exhaustion — require more invasive infra
