# inspect-5gs-sandbox

Run Inspect AI evaluations inside a complete 5G Standalone network. The active
benchmark tests whether an agent can diagnose and repair intent-driven network
slicing failures in reproducible Docker stacks running Open5GS and UERANSIM.

## Quick Start

Requirements:

- Python 3.10+
- Docker Desktop or OrbStack
- `uv`
- enough memory for at least one 5G stack, roughly 4GB

Install:

```bash
git clone https://github.com/otelcos/inspect-5gs-sandbox.git
cd inspect-5gs-sandbox
uv sync
```

Run one benchmark sample:

```bash
uv run inspect eval intent_network_slicing/network_slicing.py@three_slice_service_classes \
    --model openai/gpt-4o \
    --limit 1
```

View results:

```bash
uv run inspect view
```

The benchmark entry point is
`intent_network_slicing/network_slicing.py@three_slice_service_classes`. It
loads `intent_network_slicing/dataset.yaml`, starts the
`three_slice_service_classes` Docker Compose scenario, injects the sample fault,
runs the agent, and scores the final measured state against the formal intent.

## What The Benchmark Tests

The current experiment is not just "configure a slice." It is a closed-loop
operations task:

1. Start a healthy three-UE 5G network.
2. Inject a fault from the dataset `setup` field.
3. Give the agent diagnostic, measurement, and remediation tools.
4. Require diagnosis-first recovery of the target service.
5. Score final throughput, latency, jitter, packet loss, and collateral impact.

Current samples:

| Sample | Fault |
|---|---|
| `three_slice_service_classes_baseline` | Healthy three-UE layout |
| `three_slice_premium_service_demoted` | Premium traffic is shaped like background traffic |
| `three_slice_premium_lossy` | Premium path has packet loss on the UPF |
| `three_slice_premium_subscriber_misrouted` | Premium subscriber is mapped to the wrong slice/DNN |

The active scenario lives at
`intent_network_slicing/scenarios/three_slice_service_classes`.

## How Things Are Wired

The scenario has three active UEs. Each UE has a subscriber profile in MongoDB,
a requested S-NSSAI, a DNN, a UE container, and a dedicated iperf3 endpoint.

| UE | Role | IMSI | Slice | DNN | UE subnet | iperf3 service | Intended behavior |
|---|---|---|---|---|---|---|---|
| `ue_premium` | target | `999700000000001` | `sst=1, sd=000002` / `premium_vr` | `premium` | `10.46.20.0/24` | `iperf3-premium` | high throughput, low delay |
| `ue_control` | protected | `999700000000003` | `sst=1, sd=000003` / `protected_control` | `control` | `10.46.30.0/24` | `iperf3-control` | stable moderate service |
| `ue_background` | background | `999700000000002` | `sst=1, sd=000001` / `eMBB` | `background` | `10.46.10.0/24` | `iperf3-background` | best-effort service |

The healthy UPF service-class profile is:

| Class | Rate | Ceiling | Added delay |
|---|---:|---:|---:|
| premium | `900mbit` | `950mbit` | `2ms` |
| control | `300mbit` | `400mbit` | `8ms` |
| background | `70mbit` | `100mbit` | `35ms` |

Traffic is measured through the 5G user-plane tunnel, not directly over the
Docker bridge:

```text
UE container -> uesimtun0 -> gNB -> AMF/SMF session control -> UPF ogstun/tc -> iperf3 service
```

The background collectors run iperf3 and ping for each UE. They write rolling
measurement windows that the agent can inspect through tools and that the scorer
uses at the end of the run.

Typical healthy measurements:

| UE | Throughput | Latency |
|---|---:|---:|
| `ue_premium` | about `725 Mbit/s` | about `2.7 ms` |
| `ue_control` | about `526 Mbit/s` | about `8.8 ms` |
| `ue_background` | about `43 Mbit/s` | about `36 ms` |

When the demoted profile is injected, premium drops to roughly background-class
performance while background receives premium-like treatment. When subscriber
misrouting is injected, `ue_premium` loses `uesimtun0` and UE logs show
`DNN_NOT_SUPPORTED_OR_NOT_SUBSCRIBED`.

## Agent Tool Surface

Diagnostics:

- `diagnose_network_issue()`
- `get_logs()`
- `get_subscriber_info()`
- `get_ue_status()`
- `get_nf_status()`
- `get_network_config()`
- `get_amf_config()`
- `check_connectivity()`

Measurement:

- `measure_ue_throughput()`
- `measure_ue_latency()`
- `query_prometheus()`

Remediation:

- `apply_upf_qos_config(...)`
- `update_subscriber_slice(...)`
- `upsert_smf_slice(...)`
- `upsert_nssf_slice(...)`
- `modify_amf_config(...)`
- `restart_service(...)`
- `trigger_ue_registration(...)`
- `exec_shell(...)`

State-changing tools write to an action journal. Today the journal is mostly an
audit artifact; the roadmap is to use it for penalties such as unsafe changes,
restart storms, and collateral regressions.

## Code Map

| Path | Purpose |
|---|---|
| `intent_network_slicing/network_slicing.py` | Inspect task, system prompt, tool list, dataset loading |
| `intent_network_slicing/dataset.yaml` | Formal intents, sample inputs, fault setup commands |
| `intent_network_slicing/scorer.py` | SLA compliance scorer |
| `intent_network_slicing/intents.py` | Intent validation and metric normalization |
| `intent_network_slicing/diagnosis.py` | Root-cause inference helpers |
| `intent_network_slicing/solvers.py` | Fault injection and metrics collector startup |
| `intent_network_slicing/tools/` | Agent-visible diagnostic and remediation tools |
| `intent_network_slicing/scenarios/three_slice_service_classes/compose.yaml` | Full Docker Compose scenario |
| `intent_network_slicing/scenarios/three_slice_service_classes/config/` | Open5GS, UERANSIM, subscriber, and service-class configs |
| `intent_network_slicing/scenarios/three_slice_service_classes/scripts/` | Startup, impairment, QoS, subscriber, and metrics scripts |
| `intent_network_slicing/open5gs_sandbox/sandbox.py` | Inspect `open5gs` sandbox environment |

## Sandbox Mechanics

Each sample specifies the sandbox in `dataset.yaml`:

```yaml
sandbox: [open5gs, "three_slice_service_classes/compose.yaml"]
```

`network_slicing.py` resolves that path relative to
`intent_network_slicing/scenarios`. The `open5gs` sandbox then launches Docker
Compose and applies 5G-specific startup behavior:

1. Container startup is serialized to avoid Docker daemon overload.
2. Compose health checks bring up MongoDB, NRF, core NFs, gNB, and UEs in order.
3. A 30-second stabilization delay lets NFs register and UEs establish sessions.

Resource profile:

| Configuration | Containers | RAM | Startup |
|---|---:|---:|---:|
| Full stack | about 15 | about 4GB | about 60s |
| With Prometheus | about 16 | about 4.5GB | about 70s |

Default sandbox concurrency is `2`. Use a lower value on small machines:

```bash
uv run inspect eval intent_network_slicing/network_slicing.py@three_slice_service_classes \
    --model openai/gpt-4o \
    --max-sandboxes 1
```

## Network Functions

| Container | Role |
|---|---|
| `nrf` | NF discovery |
| `amf` | access and mobility, NGAP |
| `smf` | PDU sessions and slice/DNN mapping |
| `upf` | user-plane forwarding, `ogstun`, `tc` shaping |
| `nssf` | slice selection |
| `ausf`, `udm`, `udr`, `pcf`, `bsf` | authentication, subscriber data, policy support |
| `mongo` | Open5GS subscriber database |
| `gnb` | UERANSIM gNodeB |
| `ue_premium`, `ue_control`, `ue_background` | UERANSIM user equipment |
| `iperf3-premium`, `iperf3-control`, `iperf3-background` | per-service traffic endpoints |
| `prometheus` | optional metrics backend |

## Useful Direct Container Checks

These are useful when debugging a scenario outside the agent loop:

```python
from inspect_ai.util import sandbox

# Query subscriber database
result = await sandbox("mongo").exec([
    "mongosh", "open5gs", "--quiet", "--eval",
    "JSON.stringify(db.subscribers.find({}).toArray())",
])

# Check UE tunnel state
result = await sandbox("ue_premium").exec(["ip", "addr", "show", "uesimtun0"])

# Check AMF configuration
result = await sandbox("amf").exec(["cat", "/opt/open5gs/etc/open5gs/amf.yaml"])

# Run a tunnel-bound ping
result = await sandbox("ue_premium").exec([
    "ping", "-c", "3", "-I", "uesimtun0", "iperf3-premium",
])
```

## Known Limitations

- Open5GS has no config hot-reload; many repairs require service restarts.
- Final compliance is scored today, but recovery timing and stability-window
  scoring are still roadmap items.
- The unrestricted `exec_shell()` actuator is still available as a baseline
  capability.
- UERANSIM images are architecture-specific; adjust the compose image if your
  machine does not match the configured architecture.

## Project Documentation

- `docs/architecture.md` - architecture diagram for the active benchmark
- `docs/roadmap.md` - implementation phases and current status
- `docs/scenarios/` - fault-scenario design notes

## Further Reading

- [Inspect AI Sandboxing](https://inspect.aisi.org.uk/sandboxing.html)
- [Open5GS Documentation](https://open5gs.org/open5gs/docs/)
- [UERANSIM Wiki](https://github.com/aligungr/UERANSIM/wiki)
- [3GPP TS 23.501](https://www.3gpp.org/DynaReport/23501.htm)

## License

MIT License. See `LICENSE`.
