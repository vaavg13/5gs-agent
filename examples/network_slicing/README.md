# Network Slicing Evaluation

Evaluate AI agents on 5G network slice configuration and troubleshooting.

## Task Overview

This evaluation tests an AI agent's ability to:

- **Inspect** 5G network function configurations (AMF, SMF, UPF)
- **Diagnose** performance issues using measurement tools (iperf3, ping)
- **Troubleshoot** network impairments (latency, packet loss)
- **Verify** SLA compliance through objective measurements

## Network Architecture

```
┌──────┐        ┌─────┐        ┌─────┐        ┌─────┐
│ gNB  │◄─NGAP─►│ AMF │◄──SBI──►│ SMF │◄─PFCP─►│ UPF │
└──────┘        └─────┘        └─────┘        └─────┘
    │                                             │
    │ RRC                                         │ GTP-U (ogstun)
    │                                             │
┌──────┐                                    ┌──────────┐
│  UE  │◄───────────uesimtun0──────────────►│ iperf3   │
└──────┘           10.46.0.2                │ server   │
                                            └──────────┘
```

**Containers (15 total):**

| Container | Role |
|-----------|------|
| `nrf` | Network Repository Function (NF discovery) |
| `amf` | Access and Mobility Management (UE registration) |
| `smf` | Session Management (PDU sessions) |
| `upf` | User Plane Function (data forwarding) |
| `ausf`, `udm`, `udr` | Authentication and subscriber data |
| `pcf`, `bsf`, `nssf` | Policy, binding, slice selection |
| `gnb` | gNodeB base station (UERANSIM) |
| `ue` | User Equipment (UERANSIM) |
| `mongo` | Subscriber database |
| `iperf3-server` | Performance measurement endpoint |

## The Problem

- The UE has registered and established a PDU session
- Network may have impairments injected (latency, packet loss via `tc netem`)
- Agent must diagnose issues and ensure SLA compliance
- Success is measured by **actual iperf3/ping results**, not text matching

## Evaluation Process

### 1. Initial State

The 5G stack starts with:
- All NFs registered with NRF
- UE registered and PDU session established (`uesimtun0` interface active)
- Optional impairments injected via `setup` field in dataset

### 2. Agent Actions

The agent uses tools to:
- Query configuration (`get_amf_config`, `get_ue_status`)
- Measure performance (`measure_ue_throughput`, `measure_ue_latency`)
- Execute diagnostics (`exec_shell` to check `tc qdisc`)
- Fix issues (remove impairments, restart services)

### 3. Scoring

The scorer:
1. Runs iperf3 uplink/downlink tests
2. Runs ping for latency/jitter/packet loss
3. Compares against SLA thresholds in metadata
4. Returns fraction of metrics passing (0.0 - 1.0)

## Variants

| Variant | Difficulty | Description |
|---------|------------|-------------|
| `vr_gaming_baseline` | Easy | Verify baseline performance meets SLA |
| `vr_gaming_latency_impaired` | Medium | Remove 100ms delay from UPF (`tc netem delay 100ms`) |
| `vr_gaming_packet_loss` | Medium | Remove 5% packet loss from UPF (`tc netem loss 5%`) |

## SLA Requirements

| Metric | Target | Measurement Tool |
|--------|--------|------------------|
| Uplink throughput | ≥50 Mbps | `iperf3` |
| Downlink throughput | ≥100 Mbps | `iperf3 -R` |
| Latency | ≤20 ms | `ping` avg RTT |
| Jitter | ≤5 ms | `ping` mdev |
| Packet loss | ≤0.1% | `ping` loss% |

## Running the Evaluation

```bash
# Single variant
inspect eval network_slicing.py --model openai/gpt-4o --limit 1

# All variants
inspect eval network_slicing.py --model openai/gpt-4o

# Multiple models
inspect eval network_slicing.py --model openai/gpt-4o,anthropic/claude-sonnet-4-20250514

# View results
inspect view
```

## Available Tools

### Diagnostic Tools (`tools/retrieval.py`)

| Tool | Description |
|------|-------------|
| `get_amf_config()` | Read AMF configuration (GUAMI, TAI, slices) |
| `get_network_config()` | Read SMF/UPF/gNB configurations |
| `get_subscriber_info()` | Query subscriber database (MongoDB) |
| `get_nf_status()` | Check NF registration with NRF |
| `get_ue_status()` | Check UE registration and PDU session |
| `get_logs()` | Read container logs |
| `check_connectivity()` | Ping test through data plane |

### Action Tools (`tools/action.py`)

| Tool | Description |
|------|-------------|
| `modify_amf_config()` | Update AMF YAML configuration |
| `restart_service()` | Restart NFs after config changes |
| `trigger_ue_registration()` | Re-register UE with AMF |
| `exec_shell()` | Execute shell commands for advanced ops |

### Measurement Tools (`tools/observability.py`)

| Tool | Description |
|------|-------------|
| `measure_ue_throughput()` | iperf3 throughput (uplink/downlink) |
| `measure_ue_latency()` | ping latency/jitter/packet loss |
| `query_prometheus()` | Query metrics (requires observability profile) |

## Directory Structure

```
network_slicing/
├── network_slicing.py      # Task definition
├── scorer.py               # SLA compliance scorer
├── solvers.py              # Impairment injection solver
├── dataset.yaml            # Sample definitions with SLA targets
├── tools/
│   ├── __init__.py
│   ├── retrieval.py        # Read-only diagnostic tools
│   ├── action.py           # State-changing tools
│   └── observability.py    # Performance measurement tools
└── scenarios/
    └── vr_gaming/
        ├── compose.yaml    # Full 5G stack (15 containers)
        ├── compose-lite.yaml
        ├── config/         # NF configuration files
        │   ├── amf.yaml
        │   ├── smf.yaml
        │   ├── upf.yaml
        │   ├── gnb.yaml
        │   ├── ue.yaml
        │   └── ...
        ├── scripts/        # Container entrypoint scripts
        └── prometheus/     # Observability configuration
```

## Troubleshooting

### UE not registering

Check AMF logs:
```python
result = await sandbox("amf").exec(["journalctl", "-n", "50"])
```

### No PDU session (uesimtun0 missing)

1. Verify gNB connected to AMF: Check AMF logs for NGAP connection
2. Verify SMF/UPF ready: Check NRF for registered NFs
3. Restart UE: `trigger_ue_registration()`

### High latency or packet loss

Check for traffic control rules on UPF:
```python
result = await sandbox("upf").exec(["sh", "-c", "tc qdisc show dev ogstun"])
```

Remove impairments:
```python
await sandbox("upf").exec(["sh", "-c", "tc qdisc del dev ogstun root"])
```
