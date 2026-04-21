# Prometheus Observability Integration

This document describes the system design for Prometheus integration within the Open5GS 5G core network sandbox environment.

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Network (10.45.0.0/16)                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     5G Core Network Functions                        │   │
│  │                                                                      │   │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐         │   │
│  │   │   NRF   │    │  AUSF   │    │   UDM   │    │   UDR   │         │   │
│  │   │10.45.0.10│   │10.45.0.14│   │10.45.0.15│   │10.45.0.16│        │   │
│  │   └─────────┘    └─────────┘    └─────────┘    └─────────┘         │   │
│  │                                                                      │   │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐         │   │
│  │   │   PCF   │    │   BSF   │    │  NSSF   │    │   UPF   │         │   │
│  │   │10.45.0.17│   │10.45.0.18│   │10.45.0.19│   │10.45.0.13│        │   │
│  │   └─────────┘    └─────────┘    └─────────┘    └─────────┘         │   │
│  │                                                                      │   │
│  │   ┌──────────────────────┐    ┌──────────────────────┐              │   │
│  │   │         AMF          │    │         SMF          │              │   │
│  │   │     10.45.0.11       │    │     10.45.0.12       │              │   │
│  │   │  ┌────────────────┐  │    │  ┌────────────────┐  │              │   │
│  │   │  │ Metrics :9090  │◄─┼────┼──│ Metrics :9091  │◄─┼──────┐       │   │
│  │   │  └────────────────┘  │    │  └────────────────┘  │      │       │   │
│  │   └──────────────────────┘    └──────────────────────┘      │       │   │
│  │                                                              │       │   │
│  └──────────────────────────────────────────────────────────────┼───────┘   │
│                                                                  │           │
│  ┌───────────────────────────────────────────────────────────────┼───────┐   │
│  │                   Observability Stack (Profile)               │       │   │
│  │                                                               │       │   │
│  │   ┌──────────────────────────┐         ┌─────────────────┐   │       │   │
│  │   │       Prometheus         │         │     Grafana     │   │       │   │
│  │   │       10.45.0.30         │         │   10.45.0.31    │   │       │   │
│  │   │                          │         │                 │   │       │   │
│  │   │  scrape ─────────────────┼─────────┤►query           │   │       │   │
│  │   │  targets:                │         │ http://prom:9090│   │       │   │
│  │   │   - amf:9090 ◄───────────┼─────────┼─────────────────┘   │       │   │
│  │   │   - smf:9091 ◄───────────┼─────────┘                     │       │   │
│  │   │   - localhost:9090       │                               │       │   │
│  │   │                          │                               │       │   │
│  │   │  Port: ${PROMETHEUS_PORT │         Port: ${GRAFANA_PORT  │       │   │
│  │   │         :-9092}:9090     │               :-3000}:3000    │       │   │
│  │   └──────────────────────────┘         └─────────────────────┘       │   │
│  │                                                                       │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                          RAN Simulation                              │   │
│  │                                                                      │   │
│  │   ┌─────────────┐              ┌─────────────┐                      │   │
│  │   │     gNB     │◄────────────►│      UE     │                      │   │
│  │   │ 10.45.0.20  │   N1/N2      │ 10.45.0.21  │                      │   │
│  │   └─────────────┘              └─────────────┘                      │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

External Access (Host):
  - Prometheus UI: http://localhost:${PROMETHEUS_PORT:-9092}
  - Grafana UI:    http://localhost:${GRAFANA_PORT:-3000}
```

## Design Principles

### 1. Internal-Only Metrics Collection

Metrics endpoints on AMF and SMF are **not exposed externally**. Prometheus scrapes them via Docker's internal DNS resolution:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'open5gs-amf'
    static_configs:
      - targets: ['amf:9090']    # Docker DNS resolves to 10.45.0.11

  - job_name: 'open5gs-smf'
    static_configs:
      - targets: ['smf:9091']    # Docker DNS resolves to 10.45.0.12
```

This design provides:
- **Security**: Metrics are not exposed to the host network
- **Simplicity**: No port conflicts when running multiple stacks
- **Isolation**: Each stack has its own complete observability pipeline

### 2. Profile-Based Deployment

The observability stack is optional, controlled via Docker Compose profiles:

```yaml
# compose.yaml
prometheus:
  profiles: ["observability", "full"]
  # ...

grafana:
  profiles: ["observability", "full"]
  # ...
```

This enables:
- **Lightweight deployments**: Core 5G services only when observability isn't needed
- **Resource efficiency**: No Prometheus/Grafana overhead for automated tests
- **Flexibility**: Enable observability only for debugging sessions

### 3. Dynamic Port Configuration

External ports are configurable via environment variables:

| Service    | Environment Variable | Default | Internal Port |
|------------|---------------------|---------|---------------|
| Prometheus | `PROMETHEUS_PORT`   | 9092    | 9090          |
| Grafana    | `GRAFANA_PORT`      | 3000    | 3000          |

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           Metrics Pipeline                                │
│                                                                          │
│  1. COLLECTION                2. STORAGE              3. VISUALIZATION   │
│  ─────────────               ─────────               ────────────────    │
│                                                                          │
│  ┌─────────┐                 ┌──────────┐            ┌──────────┐       │
│  │   AMF   │ ──── scrape ───►│          │            │          │       │
│  │ :9090   │     every 5s    │          │            │          │       │
│  └─────────┘                 │          │            │          │       │
│                              │Prometheus│ ◄─ query ──│ Grafana  │       │
│  ┌─────────┐                 │   TSDB   │   PromQL   │          │       │
│  │   SMF   │ ──── scrape ───►│          │            │          │       │
│  │ :9091   │     every 5s    │          │            │          │       │
│  └─────────┘                 └──────────┘            └──────────┘       │
│                                   │                        │             │
│                                   ▼                        ▼             │
│                            prometheus_data           grafana_data        │
│                            (Docker Volume)          (Docker Volume)      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Scrape Configuration

| Job Name       | Target        | Interval | Metrics Path |
|----------------|---------------|----------|--------------|
| `open5gs-amf`  | `amf:9090`    | 5s       | `/metrics`   |
| `open5gs-smf`  | `smf:9091`    | 5s       | `/metrics`   |
| `prometheus`   | `localhost:9090` | 5s    | `/metrics`   |

## Available Metrics

### AMF Metrics (Port 9090)

| Metric | Type | Description |
|--------|------|-------------|
| `ran_ue` | Gauge | Number of connected UEs via RAN |
| `amf_session` | Gauge | Active AMF sessions |
| `gnb` | Gauge | Number of connected gNodeBs |
| `process_cpu_seconds_total` | Counter | CPU usage in seconds |
| `process_resident_memory_bytes` | Gauge | Memory usage in bytes |
| `process_open_fds` | Gauge | Open file descriptors |

### SMF Metrics (Port 9091)

| Metric | Type | Description |
|--------|------|-------------|
| `smf_session` | Gauge | Active PDU sessions |
| `process_cpu_seconds_total` | Counter | CPU usage in seconds |
| `process_resident_memory_bytes` | Gauge | Memory usage in bytes |
| `process_open_fds` | Gauge | Open file descriptors |

### Stack Identification

External labels are applied to all metrics for multi-instance disambiguation:

```yaml
global:
  external_labels:
    stack: 'open5gs_sa'
```

## Grafana Integration

### Datasource Configuration

Grafana is pre-configured to connect to Prometheus via Docker internal networking:

```yaml
# grafana/provisioning/datasources/prometheus.yml
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090    # Docker DNS resolution
    isDefault: true
```

### Pre-built Dashboard

The `Open5GS 5G Core Metrics` dashboard (`grafana/dashboards/open5gs.json`) provides:

**Stat Panels (Top Row):**
- Connected UEs (`ran_ue`)
- AMF Sessions (`amf_session`)
- Connected gNodeBs (`gnb`)
- PDU Sessions (`smf_session`)

**Time Series Panels:**
- NF CPU Usage (AMF/SMF)
- NF Memory Usage (AMF/SMF)
- Open File Descriptors
- Session Metrics Over Time

Dashboard auto-refreshes every 5 seconds with a 15-minute default time range.

## Multi-Instance Deployment

### The Problem

When running multiple Open5GS stacks in parallel (e.g., for concurrent evaluation tasks), hardcoded ports cause conflicts.

### The Solution

Each stack deploys its own isolated observability pipeline with configurable ports:

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│         Stack 1             │     │         Stack 2             │
│   (COMPOSE_PROJECT=stack1)  │     │   (COMPOSE_PROJECT=stack2)  │
│                             │     │                             │
│  ┌─────────┐  ┌─────────┐  │     │  ┌─────────┐  ┌─────────┐  │
│  │   AMF   │  │   SMF   │  │     │  │   AMF   │  │   SMF   │  │
│  │ :9090   │  │ :9091   │  │     │  │ :9090   │  │ :9091   │  │
│  └────┬────┘  └────┬────┘  │     │  └────┬────┘  └────┬────┘  │
│       │            │       │     │       │            │       │
│       ▼            ▼       │     │       ▼            ▼       │
│  ┌──────────────────────┐  │     │  ┌──────────────────────┐  │
│  │     Prometheus       │  │     │  │     Prometheus       │  │
│  │  external: 9092      │  │     │  │  external: 9093      │  │
│  └──────────────────────┘  │     │  └──────────────────────┘  │
│            │               │     │            │               │
│            ▼               │     │            ▼               │
│  ┌──────────────────────┐  │     │  ┌──────────────────────┐  │
│  │      Grafana         │  │     │  │      Grafana         │  │
│  │  external: 3000      │  │     │  │  external: 3001      │  │
│  └──────────────────────┘  │     │  └──────────────────────┘  │
│                             │     │                             │
└─────────────────────────────┘     └─────────────────────────────┘
        Host :9092,:3000                   Host :9093,:3001
```

### Usage Examples

**Single instance (default):**
```bash
docker compose --profile observability up -d
# Prometheus: http://localhost:9092
# Grafana:    http://localhost:3000
```

**Multiple instances:**
```bash
# Instance 1
PROMETHEUS_PORT=9092 GRAFANA_PORT=3000 \
  docker compose -p stack1 --profile observability up -d

# Instance 2
PROMETHEUS_PORT=9093 GRAFANA_PORT=3001 \
  docker compose -p stack2 --profile observability up -d
```

**Without observability (no port conflicts possible):**
```bash
docker compose up -d
# Only core 5G services, Prometheus/Grafana not started
```

## Programmatic Access

### Via Inspect AI Sandbox

The sandbox tools work correctly with multiple instances because they execute commands **inside** containers:

```python
# This works regardless of external port configuration
result = await sandbox["amf"].exec([
    "curl", "-s", "http://localhost:9090/metrics"
])
metrics = result.stdout
```

The routing to the correct container is handled by Inspect AI's context, not by host port mapping.

### Direct Prometheus Queries

For debugging, you can query Prometheus directly:

```bash
# From host (when observability profile is active)
curl -s "http://localhost:9092/api/v1/query?query=ran_ue"

# From inside the Docker network
docker exec <prometheus-container> \
  curl -s "http://localhost:9090/api/v1/query?query=ran_ue"
```

## Troubleshooting

### Prometheus Not Scraping Metrics

1. **Check if observability profile is enabled:**
   ```bash
   docker compose --profile observability ps
   ```

2. **Verify Prometheus can reach targets:**
   ```bash
   docker exec <prometheus-container> \
     wget -qO- http://amf:9090/metrics | head -20
   ```

3. **Check Prometheus targets page:**
   Open `http://localhost:9092/targets` in browser

### Grafana Shows No Data

1. **Verify datasource connectivity:**
   - Go to Grafana → Connections → Data sources → Prometheus
   - Click "Test" button

2. **Check if metrics exist:**
   ```bash
   curl -s "http://localhost:9092/api/v1/label/__name__/values" | jq
   ```

### Port Already in Use

```bash
# Find what's using the port
lsof -i :9092

# Use different port
PROMETHEUS_PORT=9094 docker compose --profile observability up -d
```

### Metrics Not Updating

1. **Check AMF/SMF processes are running:**
   ```bash
   docker exec <amf-container> pgrep -f open5gs-amfd
   docker exec <smf-container> pgrep -f open5gs-smfd
   ```

2. **Verify scrape interval:**
   Default is 5s. Check `prometheus.yml` if metrics seem stale.

## File Structure

```
prometheus/
├── README.md           # This document
└── prometheus.yml      # Prometheus configuration

grafana/
├── provisioning/
│   ├── datasources/
│   │   └── prometheus.yml    # Datasource auto-configuration
│   └── dashboards/
│       └── default.yml       # Dashboard provisioning config
└── dashboards/
    └── open5gs.json          # Pre-built Open5GS dashboard
```

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Open5GS Metrics](https://open5gs.org/open5gs/docs/tutorial/03-monitoring/)
- [Grafana Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Docker Compose Profiles](https://docs.docker.com/compose/profiles/)
