# Inspect Open5GS Sandbox Restructure

This document captures the complete restructuring of `inspect-5gs-sandbox` to follow the `inspect-kathara` patterns, making it easier for researchers to onboard and collaborate.

## Overview

The restructure transforms a monolithic 1,700+ LOC implementation into a clean ~150 LOC core that leverages Inspect AI's `DockerSandboxEnvironment`. Tools are relocated to examples, making each task self-contained.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Extend `DockerSandboxEnvironment`** | Inherits `exec()`, `read_file()`, `write_file()` for free |
| **Remove process pool isolation** | `DockerSandboxEnvironment` handles subprocess management correctly |
| **Health checks via Docker Compose** | Already implemented in compose.yaml with `depends_on: condition: service_healthy` |
| **Tools in examples** | Each task is self-contained; researchers can copy and modify |
| **Impairments as solvers** | Follows Kathara's `inject_faults()` pattern |
| **Observability as core** | Prometheus/Grafana is an Open5GS feature, not example-specific |

## New Directory Structure

```
inspect-5gs-sandbox/
├── src/inspect_open5gs/           # Core library (~150 LOC total)
│   ├── __init__.py                # Lazy imports
│   ├── sandbox.py                 # Open5GSSandboxEnvironment
│   ├── _observability.py          # PrometheusClient
│   ├── _util.py                   # NF_CONFIGS, utilities
│   ├── _registry.py               # Entry point registration
│   └── py.typed                   # PEP 561 marker
│
├── examples/
│   └── network_slicing/           # Complete example task
│       ├── network_slicing.py     # Task definition
│       ├── scorer.py              # SLA compliance scorer
│       ├── solvers.py             # inject_impairments()
│       ├── dataset.yaml           # Sample definitions
│       ├── tools/
│       │   ├── retrieval.py       # get_amf_config, get_logs, etc.
│       │   ├── action.py          # modify_amf_config, restart_service, etc.
│       │   └── observability.py   # measure_throughput, query_prometheus
│       └── scenarios/
│           └── vr_gaming/
│               ├── compose.yaml   # Full 5G stack
│               ├── compose-lite.yaml
│               ├── config/        # NF configurations
│               ├── scripts/       # Container entrypoints
│               └── prometheus/    # Observability config
│
├── pyproject.toml                 # Updated package config
└── tests/                         # Test files
```

## Files Deleted

The following files from the old structure were removed:

| File | LOC | Reason |
|------|-----|--------|
| `_compose_ops.py` | ~550 | Replaced by `DockerSandboxEnvironment` |
| `_health_checks.py` | ~460 | Moved to Docker Compose healthcheck directives |
| `_process_pool.py` | ~100 | Not needed with `DockerSandboxEnvironment` |
| `open5gs.py` | ~720 | Replaced by new `sandbox.py` (~90 LOC) |
| `tools/` | ~2000 | Moved to `examples/network_slicing/tools/` |
| `task_families/` | ~500 | Moved to `examples/` |
| `scorers/` | ~300 | Moved to `examples/network_slicing/` |

**Total deleted: ~4,600 LOC**

## Core Library Files

### `sandbox.py`

The core sandbox extending `DockerSandboxEnvironment`:

```python
@sandboxenv(name="open5gs")
class Open5GSSandboxEnvironment(DockerSandboxEnvironment):
    """Docker sandbox for Open5GS 5G Core with Prometheus observability."""

    @classmethod
    def default_concurrency(cls) -> int | None:
        return 2  # Each stack uses ~4GB

    @override
    @classmethod
    async def sample_init(cls, task_name, config, metadata):
        async with semaphore:
            environments = await super().sample_init(task_name, config, metadata)
            await asyncio.sleep(30)  # 5G core stabilization
        return environments

    async def get_metrics(self, query: str) -> dict[str, Any]:
        """Query Prometheus metrics."""
        ...
```

Key features:
- **Serialized startup**: Semaphore prevents Docker daemon overwhelm
- **30s stabilization delay**: Allows NF registration with NRF
- **Prometheus integration**: `get_metrics()` method for observability

### `_observability.py`

Async Prometheus client:

```python
class PrometheusClient:
    async def query(self, promql: str) -> dict[str, Any]: ...
    async def query_range(self, promql, start, end, step) -> dict[str, Any]: ...
    async def get_metric_names(self) -> list[str]: ...
    async def check_health(self) -> bool: ...
```

### `_util.py`

Network function metadata (like Kathara's `IMAGE_CONFIGS`):

```python
NF_CONFIGS = {
    "amf": {
        "image": "openverso/open5gs:2.6.4",
        "sbi_port": 7777,
        "ngap_port": 38412,
        "metrics_port": 9090,
        "config_path": "/opt/open5gs/etc/open5gs/amf.yaml",
        "healthcheck": "grep -q 38412 /proc/net/sctp/eps",
        "depends_on": ["nrf"],
    },
    # ... other NFs
}
```

### `_registry.py`

Entry point for Inspect AI:

```python
@sandboxenv(name="open5gs")
def open5gs():
    from inspect_open5gs.sandbox import Open5GSSandboxEnvironment
    return Open5GSSandboxEnvironment
```

### `__init__.py`

Lazy imports to avoid loading heavy dependencies until needed:

```python
_LAZY_IMPORTS = {
    "Open5GSSandboxEnvironment": ("sandbox", "Open5GSSandboxEnvironment"),
    "PrometheusClient": ("_observability", "PrometheusClient"),
    "NF_CONFIGS": ("_util", "NF_CONFIGS"),
    # ...
}

def __getattr__(name: str) -> object:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(...)
    module_name, attr_name = _LAZY_IMPORTS[name]
    return getattr(import_module(f"inspect_open5gs.{module_name}"), attr_name)
```

## Example Structure

### `solvers.py`

Impairment injection following Kathara's `inject_faults()` pattern:

```python
@solver
def inject_impairments() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        impairment_setup = state.metadata.get("impairment_setup", {})
        for service, script in impairment_setup.items():
            await sandbox(name=service).exec(cmd=["sh", "-c", script], timeout=30)
        return state
    return solve
```

### `dataset.yaml`

Declarative sample definitions:

```yaml
samples:
  - id: vr_gaming_latency_impaired
    input: "The VR gaming slice is experiencing high latency..."
    sandbox: [open5gs, "vr_gaming/compose.yaml"]
    metadata:
      difficulty: medium
      expected_metrics:
        uplink_throughput_mbps: 50
        max_latency_ms: 20
    setup:
      upf: "tc qdisc add dev ogstun root netem delay 100ms"
```

### Tools Pattern

Tools use `sandbox("service")` to access containers:

```python
@tool
def get_amf_config():
    async def execute(section: str | None = None) -> str:
        amf = sandbox("amf")
        result = await amf.exec(["cat", AMF_CONFIG_PATH], timeout=5)
        if not result.success:
            raise ToolError(f"Error: {result.stderr}")
        return yaml.dump(yaml.safe_load(result.stdout))
    return execute
```

### `scorer.py`

SLA compliance scoring via iperf3:

```python
@scorer(metrics=[mean(), stderr()])
def sla_compliance_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        # Check connectivity
        connected, msg = await _check_connectivity()
        if not connected:
            return Score(value=0.0, answer="Connectivity failed")

        # Collect measurements
        ul_ok, ul_mbps = await _measure_throughput("uplink")
        dl_ok, dl_mbps = await _measure_throughput("downlink")
        lat_ok, latency, jitter, loss = await _measure_latency()

        # Evaluate against SLA thresholds from metadata
        ...
    return score
```

## pyproject.toml Changes

```toml
[project]
name = "inspect-open5gs"  # Renamed from inspect-5gs-sandbox

dependencies = [
    "inspect-ai>=0.3.0",
    "aiohttp>=3.9.0",  # Added for Prometheus client
    "pyyaml>=6.0",
]

[project.entry-points.inspect_ai]
open5gs = "inspect_open5gs._registry"  # Updated entry point

[tool.hatch.build.targets.wheel]
packages = ["src/inspect_open5gs"]  # Updated package path
```

## Usage

### Running the Example

```bash
# Install dependencies
uv sync

# Run evaluation
uv run inspect eval examples/network_slicing/network_slicing.py \
    --model openai/gpt-4o \
    --limit 1
```

### Using the Sandbox in Your Own Task

```python
from inspect_ai import Task, task
from inspect_ai.agent import react

@task
def my_5g_task() -> Task:
    return Task(
        dataset=...,
        solver=[react(tools=[...])],
        sandbox=("open5gs", "path/to/compose.yaml"),
    )
```

### Accessing Containers in Tools

```python
from inspect_ai.tool import tool
from inspect_ai.util import sandbox

@tool
def my_tool():
    async def execute() -> str:
        amf = sandbox("amf")
        result = await amf.exec(["cat", "/etc/open5gs/amf.yaml"])
        return result.stdout
    return execute
```

## Comparison: Before vs After

| Metric | Before | After |
|--------|--------|-------|
| Core sandbox LOC | ~720 | ~90 |
| Total core LOC | ~1,700 | ~150 |
| Process pool isolation | Yes | No |
| Python health checks | Yes | No (Docker Compose) |
| Tools location | `src/tools/` | `examples/*/tools/` |
| DockerSandboxEnvironment | No | Yes |
| Self-contained examples | No | Yes |

## References

- [inspect-kathara](https://github.com/otelcos/inspect-kathara) - Target pattern
- [Inspect AI Documentation](https://inspect.aisi.org.uk/) - Framework docs
- [Open5GS](https://open5gs.org/) - 5G Core implementation
- [UERANSIM](https://github.com/aligungr/UERANSIM) - 5G RAN simulator
