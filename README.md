# inspect-5gs-sandbox

Run AI agent evaluations inside a complete 5G Standalone network. Test whether models can configure network slices, diagnose performance issues, and troubleshoot connectivity—all in reproducible Docker environments running Open5GS and UERANSIM.

## What is this?

This package provides [Inspect AI](https://inspect.aisi.org.uk/) integration for 5G Core Network sandboxes. You define a 5G deployment with `compose.yaml`, and Inspect AI agents can execute commands across all network functions—from AMF to UPF to the simulated UE.

## Why use this?

- **5G network configuration benchmarks** — Test whether AI agents can configure slices, modify QoS policies, and optimize network settings
- **Telco operations troubleshooting** — Evaluate models diagnosing latency, packet loss, and registration failures in realistic 5G environments
- **SLA-driven scoring** — Measure success via actual iperf3 throughput, ping latency, and packet loss—not just text matching

## Requirements

- Python 3.10+
- Docker Desktop (4GB+ RAM per stack) or OrbStack
- Inspect AI >= 0.3.0
- ARM64 or x86_64 architecture

## Installation

Clone and install from source:

```bash
git clone https://github.com/otelcos/inspect-5gs-sandbox.git
cd inspect-5gs-sandbox

# With uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Running the Example

```bash
# Make sure Docker Desktop or OrbStack is running (needs ~4GB RAM)

# Run the network slicing evaluation
uv run inspect eval examples/network_slicing/network_slicing.py \
    --model openai/gpt-4o \
    --limit 1

# View results
uv run inspect view
```

## Quick Start

### 1. Understand the 5G Stack

Each sandbox deploys a complete 5G SA network with 15 containers:

```
                            ┌─────────────────────────────────┐
                            │         Control Plane           │
                            │  NRF, AUSF, UDM, UDR, PCF,      │
                            │  BSF, NSSF, MongoDB             │
                            └─────────────────────────────────┘
                                          │ SBI (HTTP/2)
                                          ▼
┌──────┐      NGAP       ┌─────┐        SBI        ┌─────┐      PFCP       ┌─────┐
│ gNB  │◄───────────────►│ AMF │◄─────────────────►│ SMF │◄───────────────►│ UPF │
│      │   (SCTP 38412)  └─────┘                   └─────┘   (UDP 8805)    │     │
└──────┘                     │                                             └─────┘
    │                        │ N1/N2                                           │
    │ RRC                    │                                                 │ GTP-U
    │                        │                                                 │
┌──────┐                 NAS │                                          ┌──────────┐
│  UE  │◄────────────────────┘                                          │ iperf3   │
│      │                                                                │ server   │
│      │◄───────────────────Data Plane (uesimtun0)─────────────────────►│          │
└──────┘                        10.46.x.x                               └──────────┘
```

### 2. Create an evaluation task

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate
from inspect_ai.tool import tool
from inspect_ai.util import sandbox

@tool
def check_ue_status():
    """Check if UE has an active PDU session."""

    async def execute() -> str:
        ue = sandbox("ue")
        result = await ue.exec(["ip", "addr", "show", "uesimtun0"])
        if result.success:
            return f"PDU Session: ACTIVE\n{result.stdout}"
        return "PDU Session: NOT ESTABLISHED"

    return execute

@task
def network_check() -> Task:
    return Task(
        dataset=[
            Sample(
                input="Verify the UE has connectivity to the data network.",
                sandbox=("open5gs", "scenarios/vr_gaming/compose.yaml"),
            )
        ],
        solver=generate(),
    )
```

### 3. Run it

```bash
inspect eval my_eval.py --model openai/gpt-4o
```

## Configuration

### Sandbox specification

Each sample specifies its sandbox as a tuple:

```python
Sample(
    input="Configure the network slice...",
    sandbox=("open5gs", "path/to/compose.yaml"),
)
```

### Resource requirements

| Configuration | Containers | RAM    | Startup Time |
|---------------|------------|--------|--------------|
| Full stack    | 15         | ~4GB   | ~60s         |
| With metrics  | 16         | ~4.5GB | ~70s         |

### Concurrency

Default concurrency is **2 parallel stacks** (~4GB RAM each). Override via:

```bash
inspect eval my_eval.py --max-sandboxes 4
```

### Accessing containers

Use Inspect's `sandbox()` API to execute commands on any network function:

```python
from inspect_ai.util import sandbox

# Query subscriber database
result = await sandbox("mongo").exec([
    "mongosh", "open5gs", "--quiet", "--eval",
    "JSON.stringify(db.subscribers.find({}).toArray())"
])

# Check AMF configuration
result = await sandbox("amf").exec(["cat", "/opt/open5gs/etc/open5gs/amf.yaml"])

# Ping through the 5G data plane
result = await sandbox("ue").exec(["ping", "-c", "3", "-I", "uesimtun0", "iperf3-server"])

# Run iperf3 throughput test
result = await sandbox("ue").exec([
    "iperf3", "-c", "iperf3-server", "-t", "10", "-J", "--bind-dev", "uesimtun0"
])
```

## Network Functions

| Container       | Description                              | Key Port/Interface |
|-----------------|------------------------------------------|--------------------|
| `nrf`           | Network Repository Function (NF discovery) | SBI 7777           |
| `amf`           | Access and Mobility Management           | NGAP 38412         |
| `smf`           | Session Management (PDU sessions)        | PFCP 8805          |
| `upf`           | User Plane Function (data forwarding)    | ogstun interface   |
| `ausf`          | Authentication Server                    | SBI 7777           |
| `udm`           | Unified Data Management                  | SBI 7777           |
| `udr`           | Unified Data Repository                  | SBI 7777           |
| `pcf`           | Policy Control Function                  | SBI 7777           |
| `bsf`           | Binding Support Function                 | SBI 7777           |
| `nssf`          | Network Slice Selection Function         | SBI 7777           |
| `gnb`           | gNodeB base station (UERANSIM)           | NGAP               |
| `ue`            | User Equipment (UERANSIM)                | uesimtun0          |
| `mongo`         | Subscriber database                      | 27017              |
| `iperf3-server` | Performance measurement endpoint         | 5201               |

Optional (with `--profile observability`):

| Container    | Description          | Port |
|--------------|----------------------|------|
| `prometheus` | Metrics collection   | 9092 |

## How the Sandbox Works

### Startup Sequence

The sandbox extends Inspect AI's `DockerSandboxEnvironment` with 5G-specific handling:

1. **Serialized startup** — Container startup is serialized via semaphore to prevent Docker daemon overwhelm from simultaneous `compose up` calls across parallel samples

2. **Health check ordering** — Docker Compose health checks ensure proper NF startup order:
   - MongoDB starts first
   - NRF starts and waits for MongoDB
   - All other NFs wait for NRF to be healthy
   - gNB waits for AMF
   - UE waits for gNB

3. **Stabilization delay** — After containers start, a **30-second delay** allows:
   - All NFs to register with NRF
   - SBI (Service Based Interface) connections to establish
   - AMF/SMF/UPF signaling setup to complete
   - gNB to connect to AMF via NGAP
   - UE to register and establish PDU session

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Default concurrency: 2 | Each 5G stack uses ~4GB memory |
| 30s stabilization delay | 5G NFs need time beyond Docker health checks to register with NRF |
| Serialized startup | Docker daemon can't handle 100+ containers starting simultaneously |
| Privileged UPF container | Required for TUN interface (ogstun) and IP forwarding |

## Examples

- **[5G Network Slicing Tutorial](docs/5g_network_slicing.md)** — Step-by-step guide to building a slice configuration evaluation

## Known Limitations

- **Startup delay** — 5G core requires ~30s after containers start for all NFs to register with NRF. The sandbox handles this automatically.

- **Memory usage** — Each 5G stack uses ~4GB RAM. Running multiple stacks in parallel requires proportional resources.

- **No hot-reload** — Open5GS does not support configuration hot-reload. Config changes require service restarts.

- **Architecture-specific images** — UERANSIM images are architecture-specific. The compose.yaml uses `free5gc/ueransim:v4.2.0-aarch64` for ARM64. Modify for x86_64 if needed.

## Further Reading

- [Inspect AI Sandboxing](https://inspect.aisi.org.uk/sandboxing.html) — Full `sandbox()` API documentation
- [Open5GS Documentation](https://open5gs.org/open5gs/docs/) — 5G Core reference
- [UERANSIM Wiki](https://github.com/aligungr/UERANSIM/wiki) — RAN simulator details
- [3GPP TS 23.501](https://www.3gpp.org/DynaReport/23501.htm) — 5G System Architecture

## License

MIT License — see [LICENSE](./LICENSE) for details.
