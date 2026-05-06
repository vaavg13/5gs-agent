# 5GS Sandbox Architecture

This diagram reflects the active closed-loop benchmark in
`intent_network_slicing/scenarios/three_slice_service_classes`.

```mermaid
flowchart LR
    subgraph inspect["Inspect AI evaluation"]
        dataset["dataset.yaml<br/>intent + fault setup"]
        solver["solvers<br/>inject impairments<br/>start metrics collectors"]
        agent["benchmark agent<br/>5G slice engineer"]
        tools["agent tools<br/>diagnose, retrieve, measure, remediate"]
        scorer["SLA scorer<br/>intent-derived thresholds"]

        dataset --> solver --> agent
        agent <--> tools
        tools --> scorer
    end

    subgraph ran["UERANSIM RAN"]
        ue_premium["ue_premium<br/>IMSI 999700000000001<br/>slice premium_vr<br/>DNN premium"]
        ue_control["ue_control<br/>IMSI 999700000000003<br/>slice protected_control<br/>DNN control"]
        ue_background["ue_background<br/>IMSI 999700000000002<br/>slice eMBB<br/>DNN background"]
        gnb["gNB<br/>nr-gnb"]

        ue_premium <-->|"RRC / NAS"| gnb
        ue_control <-->|"RRC / NAS"| gnb
        ue_background <-->|"RRC / NAS"| gnb
    end

    subgraph core["Open5GS 5G Core"]
        nrf["NRF<br/>NF discovery"]
        amf["AMF<br/>access + mobility<br/>NGAP 38412"]
        smf["SMF<br/>PDU sessions<br/>PFCP 8805"]
        upf["UPF<br/>user plane<br/>ogstun + tc shaping"]
        nssf["NSSF<br/>slice selection"]
        ausf["AUSF<br/>authentication"]
        udm["UDM<br/>subscriber data"]
        udr["UDR<br/>data repository"]
        pcf["PCF<br/>policy control"]
        bsf["BSF<br/>binding support"]
        mongo["MongoDB<br/>Open5GS subscribers"]

        nrf <-->|"SBI HTTP/2"| amf
        nrf <-->|"SBI HTTP/2"| smf
        nrf <-->|"SBI HTTP/2"| ausf
        nrf <-->|"SBI HTTP/2"| udm
        nrf <-->|"SBI HTTP/2"| udr
        nrf <-->|"SBI HTTP/2"| pcf
        nrf <-->|"SBI HTTP/2"| bsf
        nrf <-->|"SBI HTTP/2"| nssf

        amf <-->|"N11 / SBI"| smf
        amf <-->|"slice selection"| nssf
        amf <-->|"auth services"| ausf
        ausf <-->|"subscriber auth"| udm
        udm <-->|"profile lookup"| udr
        udr <-->|"subscriber records"| mongo
        pcf <-->|"policy data"| mongo
        smf <-->|"policy / charging"| pcf
        smf <-->|"PFCP"| upf
    end

    subgraph services["Data network services"]
        iperf_premium["iperf3-premium<br/>premium endpoint"]
        iperf_control["iperf3-control<br/>control endpoint"]
        iperf_background["iperf3-background<br/>background endpoint"]
    end

    subgraph observe["Observability"]
        prometheus["Prometheus<br/>optional profile"]
        metrics_csv["/tmp/metrics.csv<br/>per-UE rolling windows"]
    end

    gnb <-->|"NGAP"| amf

    ue_premium -->|"uesimtun0 / 10.46.x.x"| upf
    ue_control -->|"uesimtun0 / 10.46.x.x"| upf
    ue_background -->|"uesimtun0 / 10.46.x.x"| upf

    upf -->|"GTP-U / routed data plane"| iperf_premium
    upf -->|"GTP-U / routed data plane"| iperf_control
    upf -->|"GTP-U / routed data plane"| iperf_background

    ue_premium -.->|"background iperf3 + ping collector"| iperf_premium
    ue_control -.->|"background iperf3 + ping collector"| iperf_control
    ue_background -.->|"background iperf3 + ping collector"| iperf_background

    ue_premium -.->|"writes"| metrics_csv
    ue_control -.->|"writes"| metrics_csv
    ue_background -.->|"writes"| metrics_csv

    prometheus -.->|"scrapes AMF :9090"| amf
    prometheus -.->|"scrapes SMF :9091"| smf
    prometheus -.->|"scrapes UPF :9092"| upf

    tools -.->|"Inspect sandbox exec/read/write"| amf
    tools -.->|"Inspect sandbox exec/read/write"| smf
    tools -.->|"Inspect sandbox exec/read/write"| nssf
    tools -.->|"subscriber mutation"| mongo
    tools -.->|"UPF service-class profile<br/>healthy / demoted / lossy"| upf
    tools -.->|"UE status + re-registration"| ue_premium
    tools -.->|"UE status + re-registration"| ue_control
    tools -.->|"UE status + re-registration"| ue_background
    tools -.->|"measure throughput / latency"| metrics_csv
    tools -.->|"PromQL"| prometheus

    scorer -.->|"reads final metrics window"| metrics_csv

    classDef eval fill:#eef4ff,stroke:#4169a8,color:#12223a;
    classDef ran fill:#edf8f4,stroke:#2b7a66,color:#10231d;
    classDef core fill:#fff4e6,stroke:#bd7a18,color:#2a1a04;
    classDef svc fill:#f7eefc,stroke:#8f4eb8,color:#24102f;
    classDef obs fill:#f3f3f3,stroke:#777,color:#222;

    class dataset,solver,agent,tools,scorer eval;
    class ue_premium,ue_control,ue_background,gnb ran;
    class nrf,amf,smf,upf,nssf,ausf,udm,udr,pcf,bsf,mongo core;
    class iperf_premium,iperf_control,iperf_background svc;
    class prometheus,metrics_csv obs;
```

## How To Read It

- **Traffic path:** each UE registers through the gNB and AMF, establishes a PDU
  session through SMF and UPF, then sends measured traffic over `uesimtun0` to
  its dedicated iperf3 endpoint.
- **Slice model:** premium, control, and background UEs map to distinct S-NSSAIs
  and DNNs, all riding the same Docker bridge network but measured through the
  5G tunnel path.
- **Closed loop:** Inspect injects a fault, starts background collectors, gives
  the agent diagnostic and remediation tools, and scores the final measurement
  window against the formal intent.
- **Actuation points:** the agent can change AMF, SMF, NSSF, Mongo subscriber
  records, UPF service-class shaping, and UE registration state.
- **Observability:** measurements primarily come from per-UE CSV collectors;
  Prometheus is optional and scrapes Open5GS metrics from AMF, SMF, and UPF.
