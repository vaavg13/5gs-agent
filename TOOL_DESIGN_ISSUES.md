# Tool Design Issues — Solution Leakage Audit

Tools, scenario descriptions, and framework components that leak the solution
to the AI agent, making the evaluation trivially easy instead of testing
real diagnosis and remediation.

## Severity Scale

- **TRIVIAL** — answer is directly stated, no reasoning needed
- **HINTS** — narrows the solution space significantly
- **CLEAN** — doesn't leak

---

## Intent Scenario (`intent_network_slicing`)

### 1. Dataset inputs state the root cause (TRIVIAL)

**File:** `examples/intent_network_slicing/dataset.yaml`

The scenario `input` fields literally name the fault:

- **`three_slice_premium_service_demoted`:**
  > "Use diagnosis to confirm the premium service class has been **demoted at the UPF**"

- **`three_slice_premium_subscriber_misrouted`:**
  > "Diagnose the **subscriber mismatch**, restore the premium **subscriber profile**"

- **`three_slice_premium_lossy`:** (moderate — says "packet loss" + "service class impaired")

**Fix:** Rewrite inputs to describe symptoms only:
- "The premium UE's network performance has degraded. Diagnose and fix."
- "The premium UE is no longer receiving its intended service level. Investigate."

### 2. `diagnose_network_issue()` returns labeled root causes (TRIVIAL)

**Files:** `diagnosis.py`, `tools/retrieval.py:66-117`

The tool runs automated checks and returns **explicit root-cause labels** with confidence:
- `"transport_impairment_upf"` — scans `tc qdisc show dev ogstun` for loss/corrupt/reorder tokens
- `"subscriber_profile_mismatch"` — compares MongoDB records against expected slice
- `"slice_config_mismatch"` — compares AMF YAML against expected slice

The agent doesn't have to reason — the tool names the exact problem and subsystem.

**Fix:** Return raw diagnostic snapshot only (tc output, config dumps, subscriber records). Remove `infer_root_causes()` from the agent-facing tool. Let the agent correlate the evidence itself.

### 3. `apply_service_class_profile` — named profile menu (HINTS)

**File:** `tools/action.py:516-566`

Takes a `profile` parameter: `"healthy"`, `"demoted"`, `"lossy_premium"`. The agent just picks `"healthy"`.

No read tool exists to inspect current QoS state — agent can't even diagnose, just guess.

**Fix:** Replace with:
1. **Read tool** `get_upf_qos_config()` — reads the service-classes YAML
2. **Write tool** `apply_upf_qos_config()` — takes YAML content or field overrides. Agent must identify which parameters are wrong and write corrected values.

### 4. Intent summary exposes expected slice config (HINTS)

**File:** `intents.py:286-338`

`format_intent_summary()` puts the target SST/SD values in the agent prompt:
> "Target slice: SST=1 SD=000002"

Combined with `get_subscriber_info()` (which returns raw MongoDB JSON with current slice assignment), the mismatch is trivially obvious.

**Fix:** Intent should inform the scorer, not be fully visible in the agent prompt. Show performance objectives (latency/throughput SLAs) but not the expected slice identifiers.

### 5. SYSTEM_PROMPT lists tool argument values (HINTS)

**File:** `network_slicing.py:59-115`

> `apply_service_class_profile: Apply the healthy or demoted UPF service-class profile`

Tells the agent the exact profile names and their meaning.

**Fix:** Generic description: "Reconfigure UPF traffic shaping parameters"

### 6. `exec_shell` bypasses all structured tools (STRUCTURAL)

**File:** `tools/action.py:634-682`

Raw shell access to any container. Agent can `tc qdisc show dev ogstun`, read config files, query MongoDB directly. Makes structured tool design partially pointless.

**Fix:** Consider whether the scorer should penalize shell usage. Or restrict which containers/commands are allowed.

### 7. `get_subscriber_info()` returns raw MongoDB JSON (HINTS)

**File:** `tools/retrieval.py:257-298`

Returns complete subscriber records with slice assignments (SST/SD). Combined with the intent showing expected slice, the mismatch requires zero reasoning.

**Fix:** Return a higher-level summary, or at minimum don't expose raw JSON that can be trivially diff'd against the intent.

---

## Basic Scenario (`network_slicing`)

### 8. Dataset targets ARE the solution (TRIVIAL)

**File:** `examples/network_slicing/dataset.yaml`

The `target` fields state the exact fix:
- `"Remove tc netem delay from UPF"`
- `"Remove tc netem loss from UPF"`

The `setup` sections expose exact impairment commands:
```yaml
setup:
  upf: "tc qdisc add dev ogstun root netem delay 100ms 10ms"
```

**Fix:** Rewrite targets as expected outcomes ("Premium UE meets latency SLA"). Remove setup details from agent-visible metadata.

### 9. README.md documents exact solutions (TRIVIAL)

**File:** `examples/network_slicing/README.md`

Variants table lists:
> `vr_gaming_latency_impaired` | Medium | Remove 100ms delay from UPF (`tc netem delay 100ms`)

And provides example commands:
```bash
tc qdisc show dev ogstun
tc qdisc del dev ogstun root
```

**Fix:** Separate evaluation documentation from files accessible during runs.

### 10. `impairment.yaml` comments name the solution (HINTS)

**File:** `scenarios/vr_gaming/config/impairment.yaml`

Comments in the file:
```yaml
# Diagnosis: Agent must discover tc is involved
# Fix: Remove traffic control rules
```

Accessible to the agent via `exec_shell` or `get_network_config`.

**Fix:** Remove comments or move config outside the container filesystem.

### 11. Impairment injection logs leak to `get_logs()` (HINTS)

**File:** `examples/network_slicing/solvers.py:47`

```python
logger.info(f"Injecting impairment on {service}: {script[:50]}...")
```

Logs the first 50 chars of "tc qdisc add dev ogstun root netem delay 100ms" — if agent reads logs, causation is revealed.

**Fix:** Suppress impairment details from logs, or log at DEBUG level only.

---

## Clean Components

| Component | Status |
|-----------|--------|
| `tools/observability.py` (measure_ue_throughput, measure_ue_latency) | CLEAN — pure measurements |
| `check_connectivity()` | CLEAN — ping pass/fail |
| `get_nf_status()` | CLEAN — NRF registration status |
| `get_logs()` (filtering mechanism) | CLEAN — neutral grep |
| `scorer.py` | CLEAN — evaluates metrics, doesn't leak to agent |
| `metrics-collector.sh` | CLEAN — CSV of measurements only |
| Basic `action.py` tools (modify_amf_config, restart_service, etc.) | CLEAN — generic, no embedded answers |

---

## Priority Order

### Must Fix (breaks evaluation validity)
1. Rewrite dataset inputs/targets to describe **symptoms only** — both scenarios
2. Remove `infer_root_causes()` from agent-facing `diagnose_network_issue()` — return raw snapshot
3. Redesign `apply_service_class_profile` → read/write QoS config tools

### Should Fix (significantly narrows solution space)
4. Stop exposing expected slice SST/SD in agent prompt — keep in scorer only
5. Clean up SYSTEM_PROMPT tool descriptions
6. Remove solution-leaking comments from config files mounted in containers

### Nice to Fix
7. Decide on `exec_shell` policy (restrict, penalize, or keep)
8. Suppress impairment injection details from logs
9. Separate README documentation from evaluation-accessible files
