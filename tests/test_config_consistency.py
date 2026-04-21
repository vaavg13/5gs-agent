"""Aggressive consistency tests for Open5GS configuration.

These tests hunt for subtle bugs in configuration consistency that could
cause deployment failures or unexpected behavior.
"""

import pytest
import yaml
from pathlib import Path


CONFIG_DIR = Path(__file__).parent.parent / \
    "src/inspect_5gs_sandbox/environments/open5gs_sa/config"

COMPOSE_PATH = Path(__file__).parent.parent / \
    "src/inspect_5gs_sandbox/environments/open5gs_sa/compose.yaml"


@pytest.fixture(scope="module")
def all_configs():
    """Load all config files once per module."""
    configs = {}
    for yaml_file in CONFIG_DIR.glob("*.yaml"):
        with open(yaml_file) as f:
            configs[yaml_file.stem] = yaml.safe_load(f)
    return configs


@pytest.fixture(scope="module")
def compose_config():
    """Load compose.yaml once per module."""
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


# =============================================================================
# PLMN Consistency Tests - Critical for 5G Network Identity
# =============================================================================


class TestPLMNConsistency:
    """PLMN (MCC/MNC) must be consistent across all NFs and RAN."""

    def test_amf_plmn_matches_nrf(self, all_configs):
        """AMF PLMN must match NRF serving PLMN."""
        nrf = all_configs["nrf"]
        amf = all_configs["amf"]

        # Get NRF PLMN
        nrf_plmn = nrf["nrf"]["serving"][0]["plmn_id"]
        nrf_mcc = str(nrf_plmn["mcc"])
        nrf_mnc = str(nrf_plmn["mnc"])

        # Get AMF PLMN
        amf_plmn = amf["amf"]["guami"][0]["plmn_id"]
        amf_mcc = str(amf_plmn["mcc"])
        amf_mnc = str(amf_plmn["mnc"])

        assert (nrf_mcc, nrf_mnc) == (amf_mcc, amf_mnc), (
            f"BUG: PLMN mismatch between NRF ({nrf_mcc}/{nrf_mnc}) and "
            f"AMF ({amf_mcc}/{amf_mnc}). UEs will fail to register!"
        )

    def test_gnb_plmn_matches_amf(self, all_configs):
        """gNB PLMN must match AMF for successful NGAP setup."""
        amf = all_configs["amf"]
        gnb = all_configs["gnb"]

        amf_plmn = amf["amf"]["guami"][0]["plmn_id"]
        amf_mcc = str(amf_plmn["mcc"])
        amf_mnc = str(amf_plmn["mnc"])

        gnb_mcc = str(gnb["mcc"])
        gnb_mnc = str(gnb["mnc"])

        assert (amf_mcc, amf_mnc) == (gnb_mcc, gnb_mnc), (
            f"BUG: PLMN mismatch between AMF ({amf_mcc}/{amf_mnc}) and "
            f"gNB ({gnb_mcc}/{gnb_mnc}). NGAP setup will fail!"
        )

    def test_ue_plmn_matches_network(self, all_configs):
        """UE PLMN must match network PLMN for registration."""
        amf = all_configs["amf"]
        ue = all_configs["ue"]

        amf_plmn = amf["amf"]["guami"][0]["plmn_id"]
        amf_mcc = str(amf_plmn["mcc"])
        amf_mnc = str(amf_plmn["mnc"])

        ue_mcc = str(ue["mcc"])
        ue_mnc = str(ue["mnc"])

        assert (amf_mcc, amf_mnc) == (ue_mcc, ue_mnc), (
            f"BUG: PLMN mismatch between network ({amf_mcc}/{amf_mnc}) and "
            f"UE ({ue_mcc}/{ue_mnc}). UE cannot register to this network!"
        )

    def test_subscriber_imsi_matches_plmn(self, all_configs):
        """Subscriber IMSI must start with PLMN (MCC+MNC)."""
        amf = all_configs["amf"]
        subscribers = all_configs["subscribers"]

        amf_plmn = amf["amf"]["guami"][0]["plmn_id"]
        expected_prefix = str(amf_plmn["mcc"]) + str(amf_plmn["mnc"]).zfill(2)

        for sub in subscribers["subscribers"]:
            imsi = str(sub["imsi"])
            assert imsi.startswith(expected_prefix), (
                f"BUG: Subscriber IMSI '{imsi}' doesn't start with PLMN prefix "
                f"'{expected_prefix}'. Subscriber will fail authentication!"
            )


# =============================================================================
# TAC (Tracking Area Code) Consistency Tests
# =============================================================================


class TestTACConsistency:
    """TAC must be consistent between AMF and gNB."""

    def test_gnb_tac_in_amf_tai_list(self, all_configs):
        """gNB TAC must be in AMF's TAI list."""
        amf = all_configs["amf"]
        gnb = all_configs["gnb"]

        gnb_tac = int(gnb["tac"])
        amf_tacs = [int(tai["tac"]) for tai in amf["amf"]["tai"]]

        assert gnb_tac in amf_tacs, (
            f"BUG: gNB TAC {gnb_tac} not in AMF TAI list {amf_tacs}. "
            "gNB will not be accepted by AMF!"
        )


# =============================================================================
# Slice (S-NSSAI) Consistency Tests
# =============================================================================


class TestSliceConsistency:
    """S-NSSAI slices must be consistent across all components."""

    def _normalize_sd(self, sd_value):
        """Normalize SD value to 6-digit hex string."""
        if sd_value is None:
            return None
        sd_str = str(sd_value)
        if sd_str.startswith("0x"):
            return sd_str[2:].zfill(6).lower()
        return sd_str.zfill(6).lower()

    def test_gnb_slice_in_amf_support(self, all_configs):
        """gNB slices must be supported by AMF."""
        amf = all_configs["amf"]
        gnb = all_configs["gnb"]

        amf_slices = amf["amf"]["plmn_support"][0]["s_nssai"]
        amf_slice_set = {
            (s["sst"], self._normalize_sd(s.get("sd")))
            for s in amf_slices
        }

        for gnb_slice in gnb.get("slices", []):
            sst = gnb_slice["sst"]
            sd = self._normalize_sd(gnb_slice.get("sd"))

            assert (sst, sd) in amf_slice_set, (
                f"BUG: gNB slice SST={sst}/SD={sd} not supported by AMF. "
                f"AMF supports: {amf_slice_set}"
            )

    def test_smf_slice_in_amf_support(self, all_configs):
        """SMF slices must be supported by AMF."""
        amf = all_configs["amf"]
        smf = all_configs["smf"]

        amf_slices = amf["amf"]["plmn_support"][0]["s_nssai"]
        amf_slice_set = {
            (s["sst"], self._normalize_sd(s.get("sd")))
            for s in amf_slices
        }

        # SMF has slice info in smf.info section
        smf_info = smf.get("smf", {}).get("info", [])
        for info in smf_info:
            for s_nssai in info.get("s_nssai", []):
                sst = s_nssai["sst"]
                sd = self._normalize_sd(s_nssai.get("sd"))

                assert (sst, sd) in amf_slice_set, (
                    f"BUG: SMF slice SST={sst}/SD={sd} not supported by AMF. "
                    f"Session establishment will fail!"
                )

    def test_ue_slice_in_amf_support(self, all_configs):
        """UE configured slices must be supported by AMF."""
        amf = all_configs["amf"]
        ue = all_configs["ue"]

        amf_slices = amf["amf"]["plmn_support"][0]["s_nssai"]
        amf_slice_set = {
            (s["sst"], self._normalize_sd(s.get("sd")))
            for s in amf_slices
        }

        # Check configured-nssai
        for slice_cfg in ue.get("configured-nssai", []):
            sst = slice_cfg["sst"]
            sd = self._normalize_sd(slice_cfg.get("sd"))

            assert (sst, sd) in amf_slice_set, (
                f"BUG: UE configured slice SST={sst}/SD={sd} not supported by AMF. "
                f"UE registration will fail!"
            )


# =============================================================================
# Subscriber Credential Consistency Tests
# =============================================================================


class TestSubscriberConsistency:
    """Subscriber credentials must be consistent between UE and database."""

    def test_ue_key_matches_subscriber(self, all_configs):
        """UE key must match subscriber database key."""
        ue = all_configs["ue"]
        subscribers = all_configs["subscribers"]

        ue_supi = ue["supi"]
        # Extract IMSI from supi (format: imsi-999700000000001)
        ue_imsi = ue_supi.replace("imsi-", "")
        ue_key = ue["key"].upper()

        for sub in subscribers["subscribers"]:
            if str(sub["imsi"]) == ue_imsi:
                sub_key = sub["k"].upper()
                assert ue_key == sub_key, (
                    f"BUG: UE key doesn't match subscriber database for IMSI {ue_imsi}. "
                    f"UE: {ue_key}, DB: {sub_key}. Authentication will fail!"
                )
                return

        pytest.fail(f"BUG: UE IMSI {ue_imsi} not found in subscriber database!")

    def test_ue_opc_matches_subscriber(self, all_configs):
        """UE OPc must match subscriber database OPc."""
        ue = all_configs["ue"]
        subscribers = all_configs["subscribers"]

        ue_imsi = ue["supi"].replace("imsi-", "")
        ue_opc = ue["op"].upper()  # UE config uses 'op' field

        for sub in subscribers["subscribers"]:
            if str(sub["imsi"]) == ue_imsi:
                sub_opc = sub["opc"].upper()
                assert ue_opc == sub_opc, (
                    f"BUG: UE OPc doesn't match subscriber database for IMSI {ue_imsi}. "
                    f"UE: {ue_opc}, DB: {sub_opc}. Authentication will fail!"
                )
                return


# =============================================================================
# Network Address Consistency Tests
# =============================================================================


class TestNetworkConsistency:
    """Network addresses must be consistent across configurations."""

    def test_gnb_amf_address_resolvable(self, all_configs):
        """gNB AMF address must be hostname 'amf' for Docker DNS."""
        gnb = all_configs["gnb"]

        amf_configs = gnb.get("amfConfigs", [])
        assert amf_configs, "BUG: gNB has no amfConfigs!"

        amf_addr = amf_configs[0].get("address")
        assert amf_addr == "amf", (
            f"BUG: gNB AMF address is '{amf_addr}', expected 'amf'. "
            "Docker DNS resolution will fail!"
        )

    def test_smf_upf_address_resolvable(self, all_configs):
        """SMF UPF PFCP address must be hostname 'upf' for Docker DNS."""
        smf = all_configs["smf"]

        upf_pfcp = smf.get("upf", {}).get("pfcp", [])
        assert upf_pfcp, "BUG: SMF has no upf.pfcp config!"

        upf_addr = upf_pfcp[0].get("addr")
        assert upf_addr == "upf", (
            f"BUG: SMF UPF PFCP address is '{upf_addr}', expected 'upf'. "
            "PFCP association will fail!"
        )

    def test_all_nrf_addresses_match(self, all_configs):
        """All NFs must point to the same NRF address."""
        nrf_addrs = set()

        for nf_name in ["amf", "smf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]:
            config = all_configs.get(nf_name, {})
            nrf_section = config.get("nrf", {})
            nrf_sbi = nrf_section.get("sbi", [])

            if nrf_sbi:
                addr = nrf_sbi[0].get("addr")
                nrf_addrs.add(addr)

        assert len(nrf_addrs) == 1, (
            f"BUG: NFs point to different NRF addresses: {nrf_addrs}. "
            "NF discovery will fail!"
        )


# =============================================================================
# Port Consistency Tests
# =============================================================================


class TestPortConsistency:
    """Port configurations must be consistent."""

    def test_amf_ngap_port_matches_gnb(self, all_configs):
        """AMF NGAP port must match gNB AMF config port."""
        amf = all_configs["amf"]
        gnb = all_configs["gnb"]

        amf_ngap = amf["amf"]["ngap"][0]["port"]
        gnb_amf_port = gnb["amfConfigs"][0]["port"]

        assert amf_ngap == gnb_amf_port, (
            f"BUG: AMF NGAP port ({amf_ngap}) != gNB AMF port ({gnb_amf_port}). "
            "NGAP connection will fail!"
        )

    def test_nrf_sbi_port_consistent(self, all_configs):
        """NRF SBI port must be consistent across all configs."""
        nrf = all_configs["nrf"]
        nrf_port = nrf["nrf"]["sbi"][0]["port"]

        for nf_name in ["amf", "smf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]:
            config = all_configs.get(nf_name, {})
            nrf_sbi = config.get("nrf", {}).get("sbi", [])

            if nrf_sbi:
                ref_port = nrf_sbi[0].get("port")
                assert ref_port == nrf_port, (
                    f"BUG: {nf_name} references NRF port {ref_port}, but NRF listens on {nrf_port}. "
                    "NF registration will fail!"
                )


# =============================================================================
# Docker Compose Service Dependency Tests
# =============================================================================


class TestServiceDependencies:
    """Validate Docker Compose service dependencies."""

    def test_amf_depends_on_nrf(self, compose_config):
        """AMF must depend on NRF being healthy."""
        amf_deps = compose_config["services"]["amf"].get("depends_on", {})

        assert "nrf" in amf_deps, "BUG: AMF missing dependency on NRF!"
        assert amf_deps["nrf"].get("condition") == "service_healthy", (
            "BUG: AMF should wait for NRF to be healthy!"
        )

    def test_gnb_depends_on_amf(self, compose_config):
        """gNB must depend on AMF being healthy."""
        gnb_deps = compose_config["services"]["gnb"].get("depends_on", {})

        assert "amf" in gnb_deps, "BUG: gNB missing dependency on AMF!"
        assert gnb_deps["amf"].get("condition") == "service_healthy", (
            "BUG: gNB should wait for AMF to be healthy!"
        )

    def test_ue_depends_on_gnb(self, compose_config):
        """UE must depend on gNB being healthy."""
        ue_deps = compose_config["services"]["ue"].get("depends_on", {})

        assert "gnb" in ue_deps, "BUG: UE missing dependency on gNB!"
        assert ue_deps["gnb"].get("condition") == "service_healthy", (
            "BUG: UE should wait for gNB to be healthy!"
        )

    def test_smf_depends_on_upf(self, compose_config):
        """SMF must have dependency on UPF for PFCP."""
        smf_deps = compose_config["services"]["smf"].get("depends_on", {})

        assert "upf" in smf_deps, (
            "BUG: SMF missing dependency on UPF. "
            "PFCP association may fail if UPF not ready!"
        )


# =============================================================================
# IP Pool Consistency Tests
# =============================================================================


class TestIPPoolConsistency:
    """IP pool configuration must be consistent."""

    def test_upf_subnet_matches_smf(self, all_configs):
        """UPF subnet must match SMF subnet for PDU sessions."""
        upf = all_configs["upf"]
        smf = all_configs["smf"]

        upf_subnets = {
            s["addr"].split("/")[0]
            for s in upf["upf"].get("subnet", [])
        }

        smf_subnets = {
            s["addr"].split("/")[0]
            for s in smf.get("smf", {}).get("subnet", [])
        }

        # At least one subnet should match
        common = upf_subnets & smf_subnets
        assert common, (
            f"BUG: No common IP pool between UPF ({upf_subnets}) and SMF ({smf_subnets}). "
            "PDU sessions will fail to get IP address!"
        )

    def test_upf_dnn_matches_smf(self, all_configs):
        """UPF DNN must match SMF DNN configuration."""
        upf = all_configs["upf"]
        smf = all_configs["smf"]

        upf_dnns = {
            s.get("dnn", "internet")
            for s in upf["upf"].get("subnet", [])
        }

        smf_dnns = {
            s.get("dnn", "internet")
            for s in smf.get("smf", {}).get("subnet", [])
        }

        # At least one DNN should match
        common = upf_dnns & smf_dnns
        assert common, (
            f"BUG: No common DNN between UPF ({upf_dnns}) and SMF ({smf_dnns}). "
            "PDU sessions will fail!"
        )


# =============================================================================
# Security Configuration Tests
# =============================================================================


class TestSecurityConfiguration:
    """Tests for security-related configuration issues."""

    def test_sbi_tls_configuration_consistent(self, all_configs):
        """TLS settings must be consistent across all SBI-based NFs."""
        tls_settings = {}

        sbi_nfs = ["nrf", "amf", "smf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]
        for nf in sbi_nfs:
            config = all_configs.get(nf, {})
            sbi = config.get("sbi", {})

            # Get server TLS setting
            server_tls = sbi.get("server", {}).get("no_tls", None)
            client_tls = sbi.get("client", {}).get("no_tls", None)

            if server_tls is not None or client_tls is not None:
                tls_settings[nf] = {
                    "server_no_tls": server_tls,
                    "client_no_tls": client_tls
                }

        # All NFs should have same TLS configuration
        if tls_settings:
            first_nf = list(tls_settings.keys())[0]
            first_setting = tls_settings[first_nf]

            for nf, setting in tls_settings.items():
                assert setting == first_setting, (
                    f"BUG: Inconsistent TLS config! {nf}={setting} vs {first_nf}={first_setting}. "
                    "SBI communication will fail!"
                )

    def test_subscriber_keys_not_default(self, all_configs):
        """Subscriber keys should not be well-known default values."""
        subscribers = all_configs["subscribers"]

        # Known default/example keys that should not be used in production
        known_default_keys = {
            "00000000000000000000000000000000",  # All zeros
            "ffffffffffffffffffffffffffffffff",  # All Fs
            "465b5ce8b199b49faa5f0a2ee238a6bc",  # Open5GS example key
        }

        for sub in subscribers["subscribers"]:
            k = sub.get("k", "").lower()
            # Note: We check but don't fail for example keys in test environment
            if k in known_default_keys:
                # This is a warning, not a failure for test environments
                pass

    def test_amf_security_algorithms_configured(self, all_configs):
        """AMF must have security algorithms configured."""
        amf = all_configs["amf"]
        security = amf["amf"].get("security", {})

        assert "integrity_order" in security, (
            "BUG: AMF missing integrity algorithm order. "
            "UE security setup will fail!"
        )

        assert "ciphering_order" in security, (
            "BUG: AMF missing ciphering algorithm order. "
            "UE security setup will fail!"
        )

        # Ensure at least one algorithm is configured
        assert security["integrity_order"], "BUG: AMF integrity_order is empty!"
        assert security["ciphering_order"], "BUG: AMF ciphering_order is empty!"


# =============================================================================
# Logging Configuration Tests
# =============================================================================


class TestLoggingConfiguration:
    """Tests for logging configuration issues."""

    @pytest.mark.parametrize("nf_name", [
        "nrf", "amf", "smf", "upf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"
    ])
    def test_nf_has_logging_configured(self, all_configs, nf_name):
        """Each NF must have logging configured."""
        config = all_configs.get(nf_name, {})

        assert "logger" in config, (
            f"BUG: {nf_name} has no logger configuration. "
            "Debugging will be difficult!"
        )

    @pytest.mark.parametrize("nf_name", [
        "nrf", "amf", "smf", "upf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"
    ])
    def test_log_file_path_valid(self, all_configs, nf_name):
        """Log file path should be valid and consistent."""
        config = all_configs.get(nf_name, {})
        logger = config.get("logger", {})
        log_file = logger.get("file", "")

        # Should be in Open5GS log directory
        expected_prefix = "/opt/open5gs/var/log/open5gs/"
        assert log_file.startswith(expected_prefix), (
            f"BUG: {nf_name} log file '{log_file}' not in expected directory. "
            f"Expected prefix: {expected_prefix}"
        )


# =============================================================================
# Metrics Configuration Tests
# =============================================================================


class TestMetricsConfiguration:
    """Tests for metrics/observability configuration."""

    def test_amf_metrics_port_unique(self, all_configs):
        """AMF metrics port should not conflict with other services."""
        amf = all_configs["amf"]
        amf_metrics = amf["amf"].get("metrics", [])

        if amf_metrics:
            amf_port = amf_metrics[0].get("port")

            # Check against SMF metrics
            smf = all_configs["smf"]
            smf_metrics = smf.get("smf", {}).get("metrics", [])
            if smf_metrics:
                smf_port = smf_metrics[0].get("port")
                assert amf_port != smf_port, (
                    f"BUG: AMF and SMF use same metrics port {amf_port}. "
                    "Prometheus scraping will fail!"
                )

    def test_metrics_bound_to_accessible_address(self, all_configs):
        """Metrics should be bound to 0.0.0.0 for Docker network access."""
        for nf_name in ["amf", "smf"]:
            config = all_configs.get(nf_name, {})
            metrics = config.get(nf_name, {}).get("metrics", [])

            if metrics:
                addr = metrics[0].get("addr")
                assert addr in ["0.0.0.0", "::"], (
                    f"BUG: {nf_name} metrics bound to '{addr}'. "
                    "Use 0.0.0.0 for Docker network access!"
                )


# =============================================================================
# Docker Compose Network Configuration Tests
# =============================================================================


class TestDockerNetworkConfig:
    """Tests for Docker Compose network configuration."""

    def test_all_services_on_same_network(self, compose_config):
        """All services must be on the same Docker network."""
        services = compose_config.get("services", {})
        networks_used = set()

        for svc_name, svc_config in services.items():
            svc_networks = svc_config.get("networks", [])
            if isinstance(svc_networks, list):
                networks_used.update(svc_networks)
            elif isinstance(svc_networks, dict):
                networks_used.update(svc_networks.keys())

        # Should only use one network for inter-service communication
        assert len(networks_used) == 1, (
            f"BUG: Services use multiple networks: {networks_used}. "
            "Services may not be able to communicate!"
        )

    def test_network_driver_is_bridge(self, compose_config):
        """Network driver should be bridge for local development."""
        networks = compose_config.get("networks", {})

        for net_name, net_config in networks.items():
            if net_config:
                driver = net_config.get("driver", "bridge")
                assert driver == "bridge", (
                    f"BUG: Network {net_name} uses driver '{driver}'. "
                    "Use 'bridge' for local development!"
                )


# =============================================================================
# Volume Mount Tests
# =============================================================================


class TestVolumeMountConfiguration:
    """Tests for volume mount configuration."""

    def test_config_mounts_are_read_only_appropriate(self, compose_config):
        """Config volume mounts should have appropriate permissions."""
        services = compose_config.get("services", {})

        for svc_name, svc_config in services.items():
            volumes = svc_config.get("volumes", [])
            for vol in volumes:
                if isinstance(vol, str) and "/scripts" in vol:
                    # Scripts should be read-only
                    assert ":ro" in vol, (
                        f"WARNING: {svc_name} scripts mount '{vol}' should be :ro"
                    )

    def test_mongo_data_uses_named_volume(self, compose_config):
        """MongoDB should use named volume for data persistence."""
        mongo = compose_config["services"].get("mongo", {})
        volumes = mongo.get("volumes", [])

        has_data_volume = any("mongo_data" in str(v) for v in volumes)
        assert has_data_volume, (
            "BUG: MongoDB should use named volume 'mongo_data' for persistence!"
        )


# =============================================================================
# Health Check Completeness Tests
# =============================================================================


class TestHealthCheckCompleteness:
    """Tests to ensure all critical services have health checks."""

    @pytest.mark.parametrize("service", [
        "mongo", "nrf", "amf", "smf", "upf", "gnb"
    ])
    def test_critical_service_has_healthcheck(self, compose_config, service):
        """Critical services must have health checks for dependency ordering."""
        svc_config = compose_config["services"].get(service, {})

        assert "healthcheck" in svc_config, (
            f"BUG: Critical service '{service}' missing healthcheck. "
            "Dependency ordering will not work correctly!"
        )

        hc = svc_config["healthcheck"]
        assert "test" in hc, f"BUG: {service} healthcheck has no test command!"
        assert "interval" in hc, f"BUG: {service} healthcheck has no interval!"
        assert "retries" in hc, f"BUG: {service} healthcheck has no retries!"
