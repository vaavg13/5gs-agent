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

from ._validation import VALID_SERVICES

# Standard config path
AMF_CONFIG_PATH = "/opt/open5gs/etc/open5gs/amf.yaml"

# 3GPP validation rules
VALIDATION_RULES = {
    "tac": {"min": 1, "max": 16777215},
    "region": {"min": 0, "max": 255},
    "set": {"min": 0, "max": 1023},
    "pointer": {"min": 0, "max": 63},
    "sst": {"min": 0, "max": 255},
}


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

        # Write updated config
        new_yaml = yaml.dump(data, default_flow_style=False)
        write_result = await amf.exec(
            ["sh", "-c", f"cat > {AMF_CONFIG_PATH} << 'EOF'\n{new_yaml}EOF"],
            timeout=5,
        )

        if not write_result.success:
            raise ToolError(f"Error writing AMF config: {write_result.stderr}")

        return (
            f"Updated AMF configuration:\n"
            f"  Field: {field_path}\n"
            f"  Old: {old_value}\n"
            f"  New: {converted_value}\n\n"
            f"Run restart_service('amf') for changes to take effect."
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

        valid_services = {"amf", "smf", "upf", "nrf", "gnb", "ue"}
        if service not in valid_services:
            return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(valid_services))}"

        sb = sandbox(service)

        # Kill the main process - Docker will restart it
        if service in ("gnb", "ue"):
            kill_cmd = f"pkill -f nr-{service}"
        else:
            kill_cmd = f"pkill -f open5gs-{service}d"

        result = await sb.exec(["sh", "-c", kill_cmd], timeout=10)

        # Wait for restart
        await asyncio.sleep(5)

        # Verify it's running
        if service in ("gnb", "ue"):
            check_cmd = f"pgrep -f nr-{service}"
        else:
            check_cmd = f"pgrep -f open5gs-{service}d"

        check_result = await sb.exec(["sh", "-c", check_cmd], timeout=5)

        if check_result.success:
            return f"Service '{service}' restarted successfully"
        else:
            return f"Service '{service}' restart initiated but process not found. May need more time."

    return execute


@tool
def trigger_ue_registration():
    """Trigger UE registration to the network.

    Use after AMF or subscriber configuration changes to re-register the UE.
    """

    async def execute() -> str:
        """Trigger UE to re-register with the network.

        Returns:
            Registration status.
        """
        ue = sandbox("ue")

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
            return f"UE registration successful. IP: {ip}"
        else:
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

        return output or "(no output)"

    return execute
