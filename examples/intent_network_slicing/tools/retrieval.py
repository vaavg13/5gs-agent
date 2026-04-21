"""Retrieval tools for network slicing tasks.

Read-only diagnostic tools that query container state without modification.
"""

from __future__ import annotations

import json
import yaml

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import store_as, sandbox

from action_journal import ActionJournal
from diagnosis import (
    collect_diagnostic_snapshot,
    format_diagnosis_report,
    infer_root_causes,
)
from ._validation import VALID_SERVICES
from ._ue_path import prepare_tunnel_path

# Standard config paths
AMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/amf.yaml"
SMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/smf.yaml"
UE_CONFIG_PATH = "/etc/ueransim/ue.yaml"


async def _resolve_imsi_from_ue_service(ue_service: str) -> str:
    """Resolve IMSI from a UE config mounted in the scenario."""
    result = await sandbox(ue_service).exec(["cat", UE_CONFIG_PATH], timeout=5)
    if not result.success:
        raise ToolError(f"Error reading {ue_service} config: {result.stderr}")

    try:
        ue_config = yaml.safe_load(result.stdout) or {}
    except Exception as exc:
        raise ToolError(f"Error parsing {ue_service} YAML: {exc}") from exc

    supi = str(ue_config.get("supi", "")).strip()
    if not supi.startswith("imsi-"):
        raise ToolError(f"Unable to resolve IMSI from {ue_service} config")
    return supi[5:]


def _normalize_service_alias(service: str) -> str:
    """Map legacy service aliases to concrete service names."""
    clean = service.lower().strip()
    if clean == "ue":
        return "ue_premium"
    return clean


def _log_path_for_service(service: str) -> str | None:
    """Return the preferred log file path for a service if one exists."""
    if service in {"amf", "ausf", "bsf", "nrf", "nssf", "pcf", "smf", "udm", "udr", "upf"}:
        return f"/opt/open5gs/var/log/open5gs/{service}.log"
    if service.startswith("ue_"):
        return "/var/log/ueransim/ue.log"
    if service == "gnb":
        return "/var/log/ueransim/gnb.log"
    return None


@tool
def diagnose_network_issue():
    """Produce a structured diagnosis before remediation.

    This tool correlates UE, subscriber, AMF, NRF, and UPF state to produce
    explicit root-cause hypotheses for the agent to evaluate.
    """

    async def execute(
        ue_service: str = "ue_premium",
        expected_sst: int | None = None,
        expected_sd: str | None = None,
        imsi: str | None = None,
        include_snapshot: bool = False,
    ) -> str:
        """Diagnose the current fault state.

        Args:
            ue_service: UE container to inspect (for example `ue_premium`)
            expected_sst: Optional expected slice SST from the intent
            expected_sd: Optional expected slice SD from the intent
            imsi: Optional IMSI to focus subscriber checks
            include_snapshot: Include raw structured snapshot as JSON

        Returns:
            Diagnosis report with ranked hypotheses.
        """
        expected_slice = None
        if expected_sst is not None or expected_sd is not None:
            if expected_sst is None or expected_sd is None:
                return "Both expected_sst and expected_sd are required when specifying an expected slice"
            try:
                expected_slice = {
                    "sst": int(expected_sst),
                    "sd": str(expected_sd),
                }
            except (TypeError, ValueError):
                return "Invalid expected slice values"

        snapshot = await collect_diagnostic_snapshot(
            ue_service=ue_service,
            imsi=imsi,
            expected_slice=expected_slice,
        )
        hypotheses = infer_root_causes(snapshot)
        report = format_diagnosis_report(snapshot, hypotheses)

        if include_snapshot:
            report += "\n\nSnapshot:\n" + json.dumps(snapshot, indent=2, sort_keys=True)

        return report

    return execute


@tool
def get_action_journal():
    """Return the current per-sample action journal.

    Useful for debugging structured tools and later for scorer development.
    """

    async def execute() -> str:
        """Render the current action journal as JSON."""
        journal = store_as(ActionJournal)
        payload = [
            entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry.dict()
            for entry in journal.actions
        ]
        return json.dumps(payload, indent=2, sort_keys=True)

    return execute


@tool
def get_amf_config():
    """Read AMF configuration.

    Use this to check GUAMI, TAI, NGAP settings, and configured slices (S-NSSAI).
    """

    async def execute(section: str | None = None) -> str:
        """Read AMF configuration from YAML.

        Args:
            section: Optional section (guami, tai, ngap, plmn_support, nrf).
                     If None, returns full configuration summary.

        Returns:
            AMF configuration in readable format.
        """
        amf = sandbox("amf")
        result = await amf.exec(["cat", AMF_CONFIG_PATH], timeout=5)

        if not result.success:
            raise ToolError(f"Error reading AMF config: {result.stderr}")

        try:
            data = yaml.safe_load(result.stdout)
        except Exception as e:
            raise ToolError(f"Error parsing YAML: {e}")

        amf_config = data.get("amf", {})
        if not amf_config:
            raise ToolError("No 'amf' section found in configuration")

        if section:
            section = section.lower().strip()
            if section not in amf_config:
                raise ToolError(f"Section '{section}' not found in AMF config")
            return yaml.dump({section: amf_config[section]}, default_flow_style=False)

        # Return summary
        lines = ["=== AMF Configuration Summary ==="]

        # GUAMI
        for i, guami in enumerate(amf_config.get("guami", [])):
            plmn = guami.get("plmn_id", {})
            amf_id = guami.get("amf_id", {})
            lines.append(
                f"GUAMI[{i}]: {plmn.get('mcc')}-{plmn.get('mnc')} "
                f"region={amf_id.get('region')} set={amf_id.get('set')} pointer={amf_id.get('pointer')}"
            )

        # TAI
        for i, tai in enumerate(amf_config.get("tai", [])):
            plmn = tai.get("plmn_id", {})
            tac = tai.get("tac", [])
            lines.append(f"TAI[{i}]: {plmn.get('mcc')}-{plmn.get('mnc')} TAC={tac}")

        # Slices
        for plmn in amf_config.get("plmn_support", []):
            for snssai in plmn.get("s_nssai", []):
                sd = snssai.get("sd", "")
                sd_str = f" SD={sd}" if sd else ""
                lines.append(f"Slice: SST={snssai.get('sst')}{sd_str}")

        return "\n".join(lines)

    return execute


@tool
def get_network_config():
    """Read network function configurations (SMF, UPF, gNB).

    Use this to check session configuration, QoS settings, and network topology.
    """

    async def execute(nf: str = "smf", service: str | None = None) -> str:
        """Read network function configuration.

        Args:
            nf: Network function to query (smf, upf, gnb, ue)
            service: Optional service override for UE-specific containers

        Returns:
            Configuration summary for the network function.
        """
        if not isinstance(nf, str):
            return f"Invalid nf type: expected string, got {type(nf).__name__}"

        nf = nf.lower().strip()

        config_paths = {
            "smf": ("/opt/open5gs/etc/open5gs/smf.yaml", "smf"),
            "upf": ("/opt/open5gs/etc/open5gs/upf.yaml", "upf"),
            "gnb": ("/etc/ueransim/gnb.yaml", "gnb"),
            "ue": ("/etc/ueransim/ue.yaml", "ue"),
        }

        if nf not in config_paths:
            return f"Invalid network function: '{nf}'. Valid options: {', '.join(sorted(config_paths.keys()))}"

        path, container = config_paths[nf]
        container_name = "gnb" if nf == "gnb" else nf
        if nf == "ue":
            container_name = service.lower().strip() if isinstance(service, str) and service.strip() else "ue_premium"
            if container_name not in VALID_SERVICES:
                return f"Invalid service override: '{container_name}'. Valid services: {', '.join(sorted(VALID_SERVICES))}"

        sb = sandbox(container_name)
        result = await sb.exec(["cat", path], timeout=5)

        if not result.success:
            raise ToolError(f"Error reading {nf} config: {result.stderr}")

        return f"=== {nf.upper()} Configuration ===\n{result.stdout}"

    return execute


def get_subscriber_info():
    """Query subscriber information from MongoDB.

    Use this to check registered subscribers, their slice assignments, and QoS profiles.
    """

    async def execute(imsi: str | None = None, ue_service: str | None = None) -> str:
        """Query subscriber database.

        Args:
            imsi: Specific IMSI to query. If omitted, all subscribers are returned unless `ue_service` is set.
            ue_service: Optional UE service name to resolve into an IMSI before querying

        Returns:
            Subscriber information.
        """
        if imsi and ue_service:
            return "Specify either imsi or ue_service, not both"

        if ue_service:
            if not isinstance(ue_service, str):
                return f"Invalid ue_service type: expected string, got {type(ue_service).__name__}"
            resolved_service = _normalize_service_alias(ue_service)
            if resolved_service not in VALID_SERVICES or not resolved_service.startswith("ue_"):
                return f"Invalid ue_service: '{ue_service}'. Valid UE services: ue_premium, ue_control, ue_background"
            imsi = await _resolve_imsi_from_ue_service(resolved_service)

        mongo = sandbox("mongo")

        if imsi:
            cmd = f"mongosh open5gs --quiet --eval 'JSON.stringify(db.subscribers.findOne({{imsi: \"{imsi}\"}}))'"
        else:
            cmd = "mongosh open5gs --quiet --eval 'JSON.stringify(db.subscribers.find({}).toArray())'"

        result = await mongo.exec(["sh", "-c", cmd], timeout=10)

        if not result.success:
            raise ToolError(f"MongoDB query failed: {result.stderr}")

        return result.stdout or "No subscribers found"

    return execute


@tool
def get_nf_status():
    """Check network function registration status.

    Queries NRF for registered network functions and their status.
    """

    async def execute() -> str:
        """Get status of all registered network functions.

        Returns:
            List of registered NFs with their status.
        """
        nrf = sandbox("nrf")

        result = await nrf.exec(
            [
                "curl",
                "-sf",
                "http://localhost:7777/nnrf-nfm/v1/nf-instances",
            ],
            timeout=10,
        )

        if not result.success:
            return "NRF query failed - network may still be initializing"

        return f"=== Registered Network Functions ===\n{result.stdout}"

    return execute


@tool
def get_ue_status():
    """Check UE registration and connection status.

    Use this to verify UE is registered and has an active PDU session.
    """

    async def execute(service: str = "ue_premium") -> str:
        """Get UE status including registration and PDU session info.

        Args:
            service: UE container to inspect (`ue_premium`, `ue_control`, or `ue_background`)

        Returns:
            UE status information.
        """
        if not isinstance(service, str):
            return f"Invalid service type: expected string, got {type(service).__name__}"

        service = _normalize_service_alias(service)
        if service not in VALID_SERVICES:
            return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(VALID_SERVICES))}"

        ue = sandbox(service)

        # Check if uesimtun0 interface exists
        result = await ue.exec(["ip", "addr", "show", "uesimtun0"], timeout=5)

        lines = [f"=== UE Status ({service}) ==="]

        if result.success:
            lines.append("PDU Session: ACTIVE")
            lines.append(f"Interface:\n{result.stdout}")
        else:
            lines.append("PDU Session: NOT ESTABLISHED")
            lines.append("The uesimtun0 interface is not present")

        # Check routes
        route_result = await ue.exec(["ip", "route"], timeout=5)
        if route_result.success:
            lines.append(f"\nRoutes:\n{route_result.stdout}")

        return "\n".join(lines)

    return execute


@tool
def get_logs():
    """Read container logs for debugging.

    Use this to diagnose issues by checking network function logs.
    """

    async def execute(
        service: str,
        lines: int = 50,
        filter_text: str | None = None,
    ) -> str:
        """Read logs from a container.

        Args:
            service: Service name (amf, smf, upf, gnb, ue, nrf)
            lines: Number of lines to retrieve (default: 50)
            filter_text: Optional text to filter logs

        Returns:
            Log output.
        """
        # Validate service parameter
        if not isinstance(service, str):
            return f"Invalid service type: expected string, got {type(service).__name__}"

        service = _normalize_service_alias(service)
        if service not in VALID_SERVICES:
            return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(VALID_SERVICES))}"

        # Validate lines parameter
        try:
            lines = int(lines)
        except (ValueError, TypeError):
            return f"Invalid lines value: '{lines}'. Must be a positive integer."

        if lines < 1 or lines > 1000:
            return f"Invalid lines value: {lines}. Must be between 1 and 1000."

        sb = sandbox(service)
        log_path = _log_path_for_service(service)
        if not log_path:
            return f"Structured log retrieval is not configured for service '{service}'"

        if filter_text:
            result = await sb.exec(
                [
                    "sh",
                    "-lc",
                    'tail -n "$1" "$2" 2>/dev/null | grep -i -F -- "$3" || true',
                    "sh",
                    str(lines),
                    log_path,
                    filter_text,
                ],
                timeout=10,
            )
        else:
            result = await sb.exec(
                ["sh", "-lc", 'tail -n "$1" "$2" 2>/dev/null || true', "sh", str(lines), log_path],
                timeout=10,
            )

        output = result.stdout.strip() if result.stdout else ""
        if not output:
            output = f"No matching log lines found in {log_path}"

        return f"=== {service.upper()} Logs ({log_path}) ===\n{output}"

    return execute


@tool
def check_connectivity():
    """Test UE connectivity through the 5G data plane.

    Verifies the UE can reach a target through the 5G core.
    """

    async def execute(
        target: str = "iperf3-server",
        count: int = 3,
        ue_service: str = "ue_premium",
    ) -> str:
        """Ping a target from the UE through uesimtun0.

        Args:
            target: Target IP or hostname (default: iperf3-server)
            count: Number of pings (default: 3)
            ue_service: UE container that should originate the ping

        Returns:
            Ping results showing connectivity status.
        """
        # Validate target parameter
        if not isinstance(target, str) or not target.strip():
            return "Invalid target: must be a non-empty string (IP or hostname)"

        target = target.strip()

        # Validate count parameter
        try:
            count = int(count)
        except (ValueError, TypeError):
            return f"Invalid count value: '{count}'. Must be a positive integer."

        if count < 1 or count > 100:
            return f"Invalid count value: {count}. Must be between 1 and 100."

        if not isinstance(ue_service, str):
            return f"Invalid ue_service type: expected string, got {type(ue_service).__name__}"

        ue_service = _normalize_service_alias(ue_service)
        if ue_service not in VALID_SERVICES:
            return f"Invalid ue_service: '{ue_service}'. Valid services: {', '.join(sorted(VALID_SERVICES))}"

        ue = sandbox(ue_service)
        try:
            target_ip, tunnel_ip = await prepare_tunnel_path(ue, target)
        except ToolError as exc:
            return f"Connectivity FAILED from {ue_service}\n{exc}"

        result = await ue.exec(
            ["ping", "-c", str(count), "-I", tunnel_ip, target_ip],
            timeout=30,
        )

        if result.success:
            return f"Connectivity OK from {ue_service} to {target_ip}\n{result.stdout}"
        else:
            return f"Connectivity FAILED from {ue_service} to {target_ip}\n{result.stderr or result.stdout}"

    return execute
