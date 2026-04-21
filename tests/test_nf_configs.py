"""Tests for Open5GS NF configuration files.

These tests validate that NF config files have correct YAML structure
for Open5GS 2.6.4.
"""

import pytest
import yaml
from pathlib import Path


CONFIG_DIR = Path(__file__).parent.parent / \
    "src/inspect_5gs_sandbox/environments/open5gs_sa/config"

# All 5G Core NFs in the sandbox
NF_NAMES = ["nrf", "amf", "smf", "upf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]

# NFs that use Service Based Interface (SBI) - excludes UPF which uses PFCP
SBI_NF_NAMES = ["nrf", "amf", "smf", "ausf", "udm", "udr", "pcf", "bsf", "nssf"]

# NFs that register with NRF via SBI (all SBI NFs except NRF itself)
NRF_REGISTERED_NFS = [nf for nf in SBI_NF_NAMES if nf != "nrf"]


@pytest.fixture
def nf_config():
    """Factory fixture to load NF config files."""
    def _load(nf_name):
        config_path = CONFIG_DIR / f"{nf_name}.yaml"
        with open(config_path) as f:
            return yaml.safe_load(f)
    return _load


# =============================================================================
# Category E: NF Config Structure Tests
# =============================================================================


class TestNFConfigStructure:
    """Validate NF config file structure."""

    @pytest.mark.parametrize("nf_name", SBI_NF_NAMES)
    def test_has_top_level_sbi_section(self, nf_config, nf_name):
        """SBI-based NF configs must have top-level sbi section.

        Note: UPF is excluded as it uses PFCP protocol, not SBI.
        """
        config = nf_config(nf_name)

        assert "sbi" in config, (
            f"BUG: {nf_name}.yaml missing top-level 'sbi' section. "
            "Required for Open5GS 2.6.4."
        )

    @pytest.mark.parametrize("nf_name", NRF_REGISTERED_NFS)
    def test_has_nrf_reference(self, nf_config, nf_name):
        """SBI-based NFs (except NRF) must have nrf section for registration.

        Note: UPF doesn't register via SBI - it uses PFCP with SMF.
        """
        config = nf_config(nf_name)

        assert "nrf" in config, (
            f"BUG: {nf_name}.yaml missing 'nrf' section. "
            "Required for NF registration."
        )

    def test_upf_uses_subnet_not_session(self, nf_config):
        """UPF config must use 'subnet' key, not 'session'."""
        config = nf_config("upf")
        upf_section = config.get("upf", {})

        assert "session" not in upf_section, (
            "BUG: UPF config uses 'session' instead of 'subnet'. "
            "Use 'subnet' for IP pool configuration."
        )

        assert "subnet" in upf_section, (
            "BUG: UPF config missing 'subnet' section for IP pool."
        )


# =============================================================================
# Category F: NF SBI Address Configuration Tests
# =============================================================================


class TestNFSbiConfiguration:
    """Validate NF SBI address configuration."""

    @pytest.mark.parametrize("nf_name", SBI_NF_NAMES)
    def test_nf_has_own_sbi_section(self, nf_config, nf_name):
        """SBI-based NF configs must have their own sbi section with address.

        Note: UPF is excluded as it uses PFCP protocol, not SBI.
        """
        config = nf_config(nf_name)
        nf_section = config.get(nf_name, {})

        assert "sbi" in nf_section, (
            f"BUG: {nf_name}.yaml missing '{nf_name}.sbi' section. "
            f"Required for service registration."
        )

    @pytest.mark.parametrize("nf_name", NRF_REGISTERED_NFS)
    def test_nrf_sbi_has_address(self, nf_config, nf_name):
        """SBI-based NFs must have nrf.sbi with address for NF discovery.

        Note: UPF is excluded as it doesn't register with NRF via SBI.
        """
        config = nf_config(nf_name)
        nrf_section = config.get("nrf", {})
        nrf_sbi = nrf_section.get("sbi", [])

        assert nrf_sbi, (
            f"BUG: {nf_name}.yaml has empty 'nrf.sbi' section. "
            "Must contain NRF address for registration."
        )

        # Check first entry has address
        if isinstance(nrf_sbi, list) and nrf_sbi:
            first_entry = nrf_sbi[0]
            assert "addr" in first_entry, (
                f"BUG: {nf_name}.yaml 'nrf.sbi' missing 'addr'. "
                "Must specify NRF hostname/IP."
            )


# =============================================================================
# Category G: Config File Existence Tests
# =============================================================================


class TestConfigFileExistence:
    """Validate all required config files exist."""

    @pytest.mark.parametrize("nf_name", NF_NAMES)
    def test_config_file_exists(self, nf_name):
        """Each NF must have a config file."""
        config_path = CONFIG_DIR / f"{nf_name}.yaml"
        assert config_path.exists(), (
            f"Missing config file: {config_path}"
        )

    def test_subscribers_config_exists(self):
        """Subscriber config file must exist."""
        config_path = CONFIG_DIR / "subscribers.yaml"
        assert config_path.exists(), (
            f"Missing subscribers config: {config_path}"
        )

    def test_gnb_config_exists(self):
        """gNB config file must exist for UERANSIM."""
        config_path = CONFIG_DIR / "gnb.yaml"
        assert config_path.exists(), (
            f"Missing gNB config: {config_path}"
        )

    def test_ue_config_exists(self):
        """UE config file must exist for UERANSIM."""
        config_path = CONFIG_DIR / "ue.yaml"
        assert config_path.exists(), (
            f"Missing UE config: {config_path}"
        )


# =============================================================================
# Category H: UPF PFCP Configuration Tests
# =============================================================================


class TestUPFConfiguration:
    """Validate UPF-specific configuration (uses PFCP, not SBI)."""

    def test_upf_has_pfcp_section(self, nf_config):
        """UPF must have pfcp section for N4 interface with SMF."""
        config = nf_config("upf")
        upf_section = config.get("upf", {})

        assert "pfcp" in upf_section, (
            "BUG: UPF config missing 'upf.pfcp' section. "
            "Required for PFCP communication with SMF."
        )

    def test_upf_pfcp_has_address(self, nf_config):
        """UPF PFCP must have address configured."""
        config = nf_config("upf")
        upf_section = config.get("upf", {})
        pfcp = upf_section.get("pfcp", [])

        assert pfcp, "BUG: UPF pfcp section is empty."

        if isinstance(pfcp, list) and pfcp:
            assert "addr" in pfcp[0], (
                "BUG: UPF pfcp missing 'addr'. Must bind to address."
            )

    def test_upf_has_gtpu_section(self, nf_config):
        """UPF must have gtpu section for user plane traffic."""
        config = nf_config("upf")
        upf_section = config.get("upf", {})

        assert "gtpu" in upf_section, (
            "BUG: UPF config missing 'upf.gtpu' section. "
            "Required for GTP-U user plane traffic."
        )


# =============================================================================
# Category I: Database Configuration Tests
# =============================================================================


class TestDatabaseConfiguration:
    """Validate database-dependent NF configurations."""

    @pytest.mark.parametrize("nf_name", ["udr", "pcf"])
    def test_has_mongodb_uri(self, nf_config, nf_name):
        """UDR and PCF must have db_uri for MongoDB connection."""
        config = nf_config(nf_name)

        assert "db_uri" in config, (
            f"BUG: {nf_name}.yaml missing 'db_uri'. "
            "Required for MongoDB connection."
        )

        assert "mongo" in config["db_uri"].lower(), (
            f"BUG: {nf_name}.yaml db_uri doesn't reference MongoDB. "
            f"Got: {config['db_uri']}"
        )
