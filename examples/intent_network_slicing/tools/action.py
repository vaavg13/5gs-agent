"""Action tools for network slicing tasks.

State-changing operations that modify container configuration or state.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import yaml

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

from action_journal import record_action
from ._validation import VALID_SERVICES

# Standard config path
AMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/amf.yaml"
SMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/smf.yaml"
NSSF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/nssf.yaml"
UPF_SERVICE_CLASS_CONFIGS = {
    "healthy": "/etc/open5gs/service-classes.yaml",
    "demoted": "/etc/open5gs/service-classes-demoted.yaml",
    "lossy_premium": "/etc/open5gs/service-classes-lossy-premium.yaml",
}

# 3GPP validation rules
VALIDATION_RULES = {
    "tac": {"min": 1, "max": 16777215},
    "region": {"min": 0, "max": 255},
    "set": {"min": 0, "max": 1023},
    "pointer": {"min": 0, "max": 63},
    "sst": {"min": 0, "max": 255},
}


def _normalize_sd(sd: str | int) -> str:
    """Normalize SD to a 6-character lowercase hex string."""
    if isinstance(sd, int):
        if sd < 0 or sd > 0xFFFFFF:
            raise ToolError("SD must be between 0 and 0xFFFFFF")
        return f"{sd:06x}"

    value = str(sd).strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    if not value or any(ch not in "0123456789abcdef" for ch in value):
        raise ToolError("SD must be hexadecimal")
    if len(value) > 6:
        raise ToolError("SD must be at most 6 hex characters")
    return value.zfill(6)


def _normalize_sst(sst: int | str) -> int:
    """Validate SST values."""
    try:
        value = int(sst)
    except (TypeError, ValueError) as exc:
        raise ToolError("SST must be an integer") from exc
    if value < 0 or value > 255:
        raise ToolError("SST must be between 0 and 255")
    return value


def _validate_dnn(dnn: str) -> str:
    """Validate DNN/APN input."""
    value = str(dnn).strip()
    if not value:
        raise ToolError("DNN must be a non-empty string")
    return value


def _validate_subnet(subnet: str) -> str:
    """Perform a lightweight CIDR validation."""
    value = str(subnet).strip()
    match = re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d{1,2}", value)
    if not match:
        raise ToolError("Subnet must be an IPv4 CIDR, e.g. 10.46.0.1/16")
    prefix = int(value.split("/")[-1])
    if prefix < 0 or prefix > 32:
        raise ToolError("Subnet prefix must be between 0 and 32")
    return value


def _parse_field_path(path: str) -> list[str | int]:
    """Parse dot-notation path into components.

    Example: "amf.tai[0].tac" -> ["amf", "tai", 0, "tac"]
    """
    components: list[str | int] = []
    for part in path.split("."):
        match = re.match(r"^(\w+)\[(\d+)\]$", part)
        if match:
            components.append(match.group(1))
            components.append(int(match.group(2)))
        else:
            components.append(part)
    return components


def _get_nested(data: dict, path: list[str | int]) -> Any:
    """Get value from nested dict using path components."""
    current: Any = data
    for component in path:
        if isinstance(component, int):
            current = current[component]
        else:
            current = current[component]
    return current


def _set_nested(data: dict, path: list[str | int], value: Any) -> None:
    """Set value in nested dict using path components."""
    current: Any = data
    for component in path[:-1]:
        current = current[component]
    current[path[-1]] = value


async def _read_yaml_config(service: str, path: str) -> dict[str, Any]:
    """Read and parse a YAML config file from a container."""
    result = await sandbox(service).exec(["cat", path], timeout=5)
    if not result.success:
        raise ToolError(f"Error reading {service} config: {result.stderr}")
    try:
        data = yaml.safe_load(result.stdout)
    except Exception as exc:
        raise ToolError(f"Error parsing {service} YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolError(f"Unexpected {service} config format")
    return data


async def _write_yaml_config(service: str, path: str, data: dict[str, Any]) -> None:
    """Write YAML config back into a container."""
    new_yaml = yaml.dump(data, default_flow_style=False)
    result = await sandbox(service).exec(
        ["sh", "-c", f"cat > {path} << 'EOF'\n{new_yaml}EOF"],
        timeout=5,
    )
    if not result.success:
        raise ToolError(f"Error writing {service} config: {result.stderr}")


@tool
def modify_amf_config():
    """Modify AMF configuration.

    Use this to update TAI, GUAMI, or slice settings.
    Changes require restart_service('amf') to take effect.

    Common paths:
    - amf.tai[0].tac - Tracking Area Code
    - amf.guami[0].amf_id.region - AMF Region ID
    - amf.plmn_support[0].s_nssai[0].sst - Slice SST
    - amf.plmn_support[0].s_nssai[0].sd - Slice SD
    """

    async def execute(field_path: str, value: str) -> str:
        """Update an AMF configuration field.

        Args:
            field_path: Dot notation path (e.g., "amf.tai[0].tac")
            value: New value for the field

        Returns:
            Confirmation of the change.
        """
        # Normalize path
        field_path = re.sub(r"\.plmn([.\[])", r".plmn_id\1", field_path)

        try:
            path_components = _parse_field_path(field_path)
        except Exception as e:
            raise ToolError(f"Invalid field path '{field_path}': {e}")

        if not path_components or path_components[0] != "amf":
            raise ToolError(f"Field path must start with 'amf'. Got: '{field_path}'")

        # Type conversion and validation
        simple_name = field_path.split(".")[-1].split("[")[0]
        if simple_name in VALIDATION_RULES:
            try:
                int_val = int(value)
                rule = VALIDATION_RULES[simple_name]
                if int_val < rule["min"] or int_val > rule["max"]:
                    raise ToolError(
                        f"Field '{simple_name}' must be between {rule['min']} and {rule['max']}"
                    )
                converted_value: Any = int_val
            except ValueError:
                raise ToolError(f"Field '{simple_name}' requires an integer value")
        else:
            # Try int conversion, fall back to string
            try:
                converted_value = int(value)
            except ValueError:
                converted_value = value

        amf = sandbox("amf")

        # Read current config
        result = await amf.exec(["cat", AMF_CONFIG_PATH], timeout=5)
        if not result.success:
            raise ToolError(f"Error reading AMF config: {result.stderr}")

        try:
            data = yaml.safe_load(result.stdout)
        except Exception as e:
            raise ToolError(f"Error parsing YAML: {e}")

        # Get old value and set new
        try:
            old_value = _get_nested(data, path_components)
            _set_nested(data, path_components, converted_value)
        except (KeyError, IndexError) as e:
            raise ToolError(f"Field path not found: {e}")

        await _write_yaml_config("amf", AMF_CONFIG_PATH, data)

        record_action(
            tool_name="modify_amf_config",
            target=f"amf:{field_path}",
            parameters={"field_path": field_path, "value": value},
            old_value=old_value,
            new_value=converted_value,
            success=True,
            restart_required=True,
            risk_class="medium",
            details="AMF configuration updated",
        )

        return (
            f"Updated AMF configuration:\n"
            f"  Field: {field_path}\n"
            f"  Old: {old_value}\n"
            f"  New: {converted_value}\n\n"
            f"Run restart_service('amf') for changes to take effect."
        )

    return execute


@tool
def upsert_smf_slice():
    """Create or update an SMF slice mapping and optional DNN subnet.

    Use this when the intent requires a slice to map to a specific DNN or
    address pool in the SMF.
    """

    async def execute(sst: int, sd: str, dnn: str, subnet: str | None = None) -> str:
        """Upsert a slice entry in `smf.info` and optionally `smf.subnet`.

        Args:
            sst: Slice/service type
            sd: Slice differentiator
            dnn: DNN/APN that should be associated with the slice
            subnet: Optional subnet CIDR for the DNN address pool

        Returns:
            Summary of the updated SMF mapping.
        """
        clean_sst = _normalize_sst(sst)
        clean_sd = _normalize_sd(sd)
        clean_dnn = _validate_dnn(dnn)
        clean_subnet = _validate_subnet(subnet) if subnet is not None else None

        data = await _read_yaml_config("smf", SMF_CONFIG_PATH)
        smf_section = data.setdefault("smf", {})
        info_entries = smf_section.setdefault("info", [])
        subnet_entries = smf_section.setdefault("subnet", [])

        old_value: dict[str, Any] = {"info": None, "subnet": None}
        updated_info = False
        for entry in info_entries:
            for slice_entry in entry.get("s_nssai", []):
                if (
                    int(slice_entry.get("sst", -1)) == clean_sst
                    and _normalize_sd(slice_entry.get("sd", "")) == clean_sd
                ):
                    old_value["info"] = {
                        "sst": slice_entry.get("sst"),
                        "sd": slice_entry.get("sd"),
                        "dnn": list(slice_entry.get("dnn", [])),
                    }
                    slice_entry["dnn"] = [clean_dnn]
                    updated_info = True
                    break
            if updated_info:
                break

        if not updated_info:
            info_entries.append(
                {
                    "s_nssai": [
                        {
                            "sst": clean_sst,
                            "sd": clean_sd,
                            "dnn": [clean_dnn],
                        }
                    ]
                }
            )

        if clean_subnet is not None:
            updated_subnet = False
            for entry in subnet_entries:
                if entry.get("dnn") == clean_dnn:
                    old_value["subnet"] = {
                        "dnn": entry.get("dnn"),
                        "addr": entry.get("addr"),
                    }
                    entry["addr"] = clean_subnet
                    updated_subnet = True
                    break
            if not updated_subnet:
                subnet_entries.append({"addr": clean_subnet, "dnn": clean_dnn})

        await _write_yaml_config("smf", SMF_CONFIG_PATH, data)

        new_value = {
            "slice": {"sst": clean_sst, "sd": clean_sd, "dnn": [clean_dnn]},
            "subnet": {"dnn": clean_dnn, "addr": clean_subnet} if clean_subnet else None,
        }
        record_action(
            tool_name="upsert_smf_slice",
            target=f"smf:slice:{clean_sst}/{clean_sd}",
            parameters={"sst": clean_sst, "sd": clean_sd, "dnn": clean_dnn, "subnet": clean_subnet},
            old_value=old_value,
            new_value=new_value,
            success=True,
            restart_required=True,
            risk_class="medium",
            details="SMF slice mapping updated",
        )

        return (
            "Updated SMF slice mapping:\n"
            f"  Slice: SST={clean_sst} SD={clean_sd}\n"
            f"  DNN: {clean_dnn}\n"
            f"  Subnet: {clean_subnet or '(unchanged)'}\n\n"
            "Run restart_service('smf') for changes to take effect."
        )

    return execute


@tool
def upsert_nssf_slice():
    """Create or update an NSSF slice selection entry."""

    async def execute(sst: int, sd: str, addr: str = "nrf", port: int = 7777) -> str:
        """Upsert a slice entry in `nssf.nsi`.

        Args:
            sst: Slice/service type
            sd: Slice differentiator
            addr: NSSF target address for the NSI entry
            port: NSSF target port for the NSI entry

        Returns:
            Summary of the updated NSSF mapping.
        """
        clean_sst = _normalize_sst(sst)
        clean_sd = _normalize_sd(sd)
        clean_addr = str(addr).strip()
        if not clean_addr:
            raise ToolError("addr must be a non-empty string")
        try:
            clean_port = int(port)
        except (TypeError, ValueError) as exc:
            raise ToolError("port must be an integer") from exc

        data = await _read_yaml_config("nssf", NSSF_CONFIG_PATH)
        nssf_section = data.setdefault("nssf", {})
        nsi_entries = nssf_section.setdefault("nsi", [])

        old_value = None
        updated = False
        for entry in nsi_entries:
            s_nssai = entry.get("s_nssai", {})
            if (
                int(s_nssai.get("sst", -1)) == clean_sst
                and _normalize_sd(s_nssai.get("sd", "")) == clean_sd
            ):
                old_value = {
                    "addr": entry.get("addr"),
                    "port": entry.get("port"),
                    "s_nssai": {
                        "sst": s_nssai.get("sst"),
                        "sd": s_nssai.get("sd"),
                    },
                }
                entry["addr"] = clean_addr
                entry["port"] = clean_port
                entry["s_nssai"] = {"sst": clean_sst, "sd": clean_sd}
                updated = True
                break

        if not updated:
            nsi_entries.append(
                {
                    "addr": clean_addr,
                    "port": clean_port,
                    "s_nssai": {"sst": clean_sst, "sd": clean_sd},
                }
            )

        await _write_yaml_config("nssf", NSSF_CONFIG_PATH, data)

        new_value = {
            "addr": clean_addr,
            "port": clean_port,
            "s_nssai": {"sst": clean_sst, "sd": clean_sd},
        }
        record_action(
            tool_name="upsert_nssf_slice",
            target=f"nssf:slice:{clean_sst}/{clean_sd}",
            parameters={"sst": clean_sst, "sd": clean_sd, "addr": clean_addr, "port": clean_port},
            old_value=old_value,
            new_value=new_value,
            success=True,
            restart_required=True,
            risk_class="medium",
            details="NSSF slice selection entry updated",
        )

        return (
            "Updated NSSF slice selection entry:\n"
            f"  Slice: SST={clean_sst} SD={clean_sd}\n"
            f"  Address: {clean_addr}:{clean_port}\n\n"
            "Run restart_service('nssf') for changes to take effect."
        )

    return execute


@tool
def restart_service():
    """Restart a network function service.

    Required after configuration changes. Open5GS does not support hot-reload.
    """

    async def execute(service: str) -> str:
        """Restart a network function.

        Args:
            service: Service name (amf, smf, upf, gnb, ue)

        Returns:
            Restart status.
        """
        if not isinstance(service, str):
            return f"Invalid service type: expected string, got {type(service).__name__}"

        service = service.lower().strip()

        valid_services = {"amf", "smf", "upf", "nrf", "gnb", "ue_premium", "ue_background", "ue_control"}
        if service not in valid_services:
            return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(valid_services))}"

        sb = sandbox(service)

        # Kill the main process - Docker will restart it
        if service == "gnb":
            kill_cmd = "pkill -f nr-gnb"
        elif service.startswith("ue_"):
            kill_cmd = "pkill -f nr-ue"
        else:
            kill_cmd = f"pkill -f open5gs-{service}d"

        result = await sb.exec(["sh", "-c", kill_cmd], timeout=10)

        # Wait for restart
        await asyncio.sleep(5)

        # Verify it's running
        if service == "gnb":
            check_cmd = "pgrep -f nr-gnb"
        elif service.startswith("ue_"):
            check_cmd = "pgrep -f nr-ue"
        else:
            check_cmd = f"pgrep -f open5gs-{service}d"

        check_result = await sb.exec(["sh", "-c", check_cmd], timeout=5)

        success = check_result.success
        details = (
            f"Service '{service}' restarted successfully"
            if success
            else "Restart initiated but process was not observed after the wait interval"
        )
        record_action(
            tool_name="restart_service",
            target=f"service:{service}",
            parameters={"service": service},
            success=success,
            restart_required=False,
            risk_class="high" if service in {"nrf", "upf", "smf", "amf"} else "medium",
            details=details,
        )

        if check_result.success:
            return f"Service '{service}' restarted successfully"
        else:
            return f"Service '{service}' restart initiated but process not found. May need more time."

    return execute


@tool
def apply_service_class_profile():
    """Apply a named UPF traffic-class profile.

    This is a structured alternative to raw shell commands for scenarios that
    differentiate premium, protected, and background service classes on the UPF.
    """

    async def execute(profile: str = "healthy") -> str:
        """Apply one of the mounted service-class profiles on the UPF.

        Args:
            profile: Named profile to apply ("healthy" or "demoted")

        Returns:
            Summary of the applied profile.
        """
        clean_profile = str(profile).strip().lower()
        if clean_profile not in UPF_SERVICE_CLASS_CONFIGS:
            valid = ", ".join(sorted(UPF_SERVICE_CLASS_CONFIGS))
            raise ToolError(f"Unknown profile '{profile}'. Valid profiles: {valid}")

        config_path = UPF_SERVICE_CLASS_CONFIGS[clean_profile]
        upf = sandbox("upf")
        result = await upf.exec(
            ["/scripts/apply-service-class-qos.sh", config_path],
            timeout=20,
        )

        success = result.success
        record_action(
            tool_name="apply_service_class_profile",
            target="upf:ogstun",
            parameters={"profile": clean_profile, "config_path": config_path},
            new_value={"profile": clean_profile},
            success=success,
            restart_required=False,
            risk_class="medium",
            details="Applied named UPF service-class profile",
        )

        if not success:
            raise ToolError(result.stderr or result.stdout or "Failed to apply service-class profile")

        return (
            f"Applied UPF service-class profile '{clean_profile}'.\n"
            f"Config: {config_path}\n\n"
            f"{result.stdout}"
        )

    return execute


@tool
def trigger_ue_registration():
    """Trigger UE registration to the network.

    Use after AMF or subscriber configuration changes to re-register the UE.
    """

    async def execute(service: str = "ue_premium") -> str:
        """Trigger UE to re-register with the network.

        Args:
            service: UE container to restart and re-register

        Returns:
            Registration status.
        """
        if not isinstance(service, str):
            return f"Invalid service type: expected string, got {type(service).__name__}"

        service = service.lower().strip()
        if service not in VALID_SERVICES or not service.startswith("ue_"):
            return f"Invalid UE service: '{service}'"

        ue = sandbox(service)

        # Kill UE process to trigger re-registration
        await ue.exec(["pkill", "-f", "nr-ue"], timeout=5)

        # Wait for restart
        await asyncio.sleep(10)

        # Check if uesimtun0 interface came up
        result = await ue.exec(["ip", "addr", "show", "uesimtun0"], timeout=5)

        if result.success and "inet " in result.stdout:
            # Extract IP address
            match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
            ip = match.group(1) if match else "unknown"
            record_action(
                tool_name="trigger_ue_registration",
                target=f"service:{service}",
                parameters={"service": service},
                new_value={"ip": ip},
                success=True,
                restart_required=False,
                risk_class="medium",
                details="UE registration succeeded after restart",
            )
            return f"UE registration successful. IP: {ip}"
        else:
            record_action(
                tool_name="trigger_ue_registration",
                target=f"service:{service}",
                parameters={"service": service},
                success=False,
                restart_required=False,
                risk_class="medium",
                details="UE restart completed but PDU session was not yet established",
            )
            return "UE registration initiated but PDU session not yet established. Check logs."

    return execute


@tool
def exec_shell():
    """Execute a shell command in a container.

    Use for advanced diagnostics or operations not covered by other tools.
    """

    async def execute(service: str, command: str) -> str:
        """Execute a shell command.

        Args:
            service: Container name (amf, smf, upf, gnb, ue, mongo, nrf)
            command: Shell command to execute

        Returns:
            Command output.
        """
        # Validate service parameter
        if not isinstance(service, str):
            return f"Invalid service type: expected string, got {type(service).__name__}"

        service = service.lower().strip()
        if service not in VALID_SERVICES:
            return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(VALID_SERVICES))}"

        # Validate command parameter
        if not isinstance(command, str) or not command.strip():
            return "Invalid command: must be a non-empty string"

        sb = sandbox(service)

        result = await sb.exec(["sh", "-c", command], timeout=30)

        output = result.stdout or ""
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"

        record_action(
            tool_name="exec_shell",
            target=f"service:{service}",
            parameters={"service": service, "command": command},
            success=result.success,
            restart_required=False,
            risk_class="critical",
            details="Unstructured shell command executed",
        )

        return output or "(no output)"

    return execute
