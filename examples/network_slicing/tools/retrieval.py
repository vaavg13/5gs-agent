"""Retrieval tools for network slicing tasks.

Read-only diagnostic tools that query container state without modification.
"""

from __future__ import annotations

import yaml

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

from ._validation import VALID_SERVICES

# Standard config paths
AMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/amf.yaml"
SMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/smf.yaml"


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

    async def execute(nf: str = "smf") -> str:
        """Read network function configuration.

        Args:
            nf: Network function to query (smf, upf, gnb, ue)

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
        container_name = "gnb" if nf in ("gnb", "ue") else nf

        sb = sandbox(container_name)
        result = await sb.exec(["cat", path], timeout=5)

        if not result.success:
            raise ToolError(f"Error reading {nf} config: {result.stderr}")

        return f"=== {nf.upper()} Configuration ===\n{result.stdout}"

    return execute


@tool
def get_subscriber_info():
    """Query subscriber information from MongoDB.

    Use this to check registered subscribers, their slice assignments, and QoS profiles.
    """

    async def execute(imsi: str | None = None) -> str:
        """Query subscriber database.

        Args:
            imsi: Specific IMSI to query. If None, lists all subscribers.

        Returns:
            Subscriber information.
        """
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

    async def execute() -> str:
        """Get UE status including registration and PDU session info.

        Returns:
            UE status information.
        """
        ue = sandbox("ue")

        # Check if uesimtun0 interface exists
        result = await ue.exec(["ip", "addr", "show", "uesimtun0"], timeout=5)

        lines = ["=== UE Status ==="]

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

        service = service.lower().strip()
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

        # Most containers use journalctl or have logs in /var/log
        # Try reading from stdout/stderr of main process
        cmd = f"journalctl -n {lines} --no-pager 2>/dev/null || tail -n {lines} /var/log/*.log 2>/dev/null || echo 'No logs available'"

        if filter_text:
            cmd += f" | grep -i '{filter_text}'"

        result = await sb.exec(["sh", "-c", cmd], timeout=10)

        return f"=== {service.upper()} Logs ===\n{result.stdout}"

    return execute


@tool
def check_connectivity():
    """Test UE connectivity to external networks.

    Verifies the UE can reach the data network through the 5G core.
    """

    async def execute(target: str = "8.8.8.8", count: int = 3) -> str:
        """Ping a target from the UE through uesimtun0.

        Args:
            target: Target IP or hostname (default: 8.8.8.8)
            count: Number of pings (default: 3)

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

        ue = sandbox("ue")

        result = await ue.exec(
            ["ping", "-c", str(count), "-I", "uesimtun0", target],
            timeout=30,
        )

        if result.success:
            return f"Connectivity OK\n{result.stdout}"
        else:
            return f"Connectivity FAILED\n{result.stderr or result.stdout}"

    return execute
