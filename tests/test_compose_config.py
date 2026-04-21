"""Tests for compose.yaml configuration correctness.

These tests validate that compose.yaml is correctly configured
to avoid common deployment issues found during development.
"""

import pytest
import yaml
from pathlib import Path


@pytest.fixture(scope="module")
def compose_config():
    """Load compose.yaml once per module."""
    compose_path = Path(__file__).parent.parent / \
        "src/inspect_5gs_sandbox/environments/open5gs_sa/compose.yaml"
    with open(compose_path) as f:
        return yaml.safe_load(f)


# =============================================================================
# Category A: Volume Mount Tests
# =============================================================================


class TestVolumeMounts:
    """Validate volume mount paths."""

    @pytest.mark.parametrize("service,expected_container_path", [
        ("nrf", "/opt/open5gs/etc/open5gs/nrf.yaml"),
        ("amf", "/opt/open5gs/etc/open5gs/amf.yaml"),
        ("smf", "/opt/open5gs/etc/open5gs/smf.yaml"),
        ("upf", "/opt/open5gs/etc/open5gs/upf.yaml"),
    ])
    def test_no_duplicate_path_prefix(self, compose_config, service, expected_container_path):
        """Volume mount should not have duplicate /opt/open5gs/ prefix."""
        volumes = compose_config["services"][service].get("volumes", [])
        config_mounts = [v for v in volumes if ".yaml:" in v]
        assert config_mounts, f"No config volume mount found for {service}"

        config_mount = config_mounts[0]
        container_path = config_mount.split(":")[1]

        assert "/opt/open5gs/opt/open5gs/" not in container_path, (
            f"BUG: Duplicate prefix in {service} volume mount. "
            f"Got: {container_path}"
        )

        assert container_path == expected_container_path, (
            f"Config mount path mismatch for {service}. "
            f"Expected: {expected_container_path}, Got: {container_path}"
        )


# =============================================================================
# Category B: Health Check Tests
# =============================================================================


class TestHealthChecks:
    """Validate health check commands use correct protocols."""

    def test_nrf_uses_http2(self, compose_config):
        """NRF health check must use --http2-prior-knowledge."""
        healthcheck = compose_config["services"]["nrf"]["healthcheck"]["test"]
        cmd = " ".join(healthcheck) if isinstance(healthcheck, list) else healthcheck

        assert "--http2-prior-knowledge" in cmd, (
            "BUG: NRF health check missing --http2-prior-knowledge. "
            "Open5GS uses HTTP/2."
        )

    def test_amf_checks_sctp_not_tcp(self, compose_config):
        """AMF health check must check SCTP (NGAP protocol)."""
        healthcheck = compose_config["services"]["amf"]["healthcheck"]["test"]
        cmd = " ".join(healthcheck) if isinstance(healthcheck, list) else healthcheck

        assert "sctp" in cmd.lower() or "/proc/net/sctp" in cmd, (
            "BUG: AMF health check should check SCTP, not TCP. "
            "NGAP uses SCTP port 38412."
        )

    def test_smf_checks_udp_not_tcp(self, compose_config):
        """SMF health check must check UDP (PFCP protocol)."""
        healthcheck = compose_config["services"]["smf"]["healthcheck"]["test"]
        cmd = " ".join(healthcheck) if isinstance(healthcheck, list) else healthcheck

        # Check for UDP indicators: -u flag for netcat, udp in ss output, or netstat -u
        is_udp_check = (
            "-u" in cmd or
            "udp" in cmd.lower() or
            "ulnp" in cmd  # netstat -ulnp or ss -ulnp
        )

        assert is_udp_check, (
            "BUG: SMF health check should check UDP, not TCP. "
            "PFCP uses UDP port 8805."
        )


# =============================================================================
# Category C: Service Configuration Tests
# =============================================================================


class TestServiceConfiguration:
    """Validate service-specific settings."""

    def test_upf_has_privileged_mode(self, compose_config):
        """UPF must have privileged: true for TUN interface."""
        upf = compose_config["services"]["upf"]

        assert upf.get("privileged") is True, (
            "BUG: UPF missing privileged: true. "
            "Required to create ogstun interface."
        )

    def test_mongodb_service_exists(self, compose_config):
        """MongoDB service must exist for UDR/PCF."""
        assert "mongo" in compose_config["services"], (
            "BUG: MongoDB service missing. UDR and PCF require MongoDB."
        )

    @pytest.mark.parametrize("service", ["udr", "pcf"])
    def test_service_depends_on_mongodb(self, compose_config, service):
        """UDR/PCF must depend on mongo:service_healthy."""
        depends_on = compose_config["services"][service].get("depends_on", {})

        has_mongo_dep = (
            "mongo" in depends_on and
            depends_on["mongo"].get("condition") == "service_healthy"
        )

        assert has_mongo_dep, (
            f"BUG: {service} missing mongo dependency with service_healthy condition."
        )


# =============================================================================
# Category D: UERANSIM Command Tests
# =============================================================================


class TestUERANSIMCommands:
    """Validate UERANSIM command format."""

    @pytest.mark.parametrize("service,invalid_prefix", [
        ("gnb", "nr-gnb"),
        ("ue", "nr-ue"),
    ])
    def test_command_does_not_include_binary(self, compose_config, service, invalid_prefix):
        """UERANSIM command should not include binary name."""
        command = compose_config["services"][service].get("command", "")
        if isinstance(command, list):
            command = " ".join(command)

        # If command is empty/None, that's fine (entrypoint handles it)
        if not command:
            return

        assert not command.startswith(invalid_prefix), (
            f"BUG: {service} command should not start with '{invalid_prefix}'. "
            "The entrypoint already handles the binary."
        )


# =============================================================================
# Category E: Prometheus Port Configuration Tests
# =============================================================================


class TestPrometheusConfiguration:
    """Validate Prometheus port configuration for multi-instance support."""

    def test_prometheus_port_is_configurable(self, compose_config):
        """Prometheus port must use environment variable for dynamic allocation."""
        prometheus = compose_config["services"].get("prometheus", {})
        ports = prometheus.get("ports", [])

        # Check if any port mapping uses PROMETHEUS_PORT variable
        port_config = " ".join(str(p) for p in ports)

        assert "PROMETHEUS_PORT" in port_config, (
            "BUG: Prometheus port should use ${PROMETHEUS_PORT:-9092} "
            "to allow parallel instances with unique ports."
        )
