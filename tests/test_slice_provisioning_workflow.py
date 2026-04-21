"""Integration tests for slice provisioning workflow.

These tests validate the complete slice provisioning workflow using
the validation tools. Tests use mocked sandbox operations.

NOTE: The validation tools (check_slice_consistency, test_slice_connectivity)
use ToolError for error cases rather than returning structured error responses.
This is different from the MongoDB tools which return structured dicts.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from inspect_ai.tool import ToolError


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_amf_config():
    """Sample AMF configuration with existing slice."""
    return """
amf:
  plmn_support:
    - plmn_id:
        mcc: 999
        mnc: 70
      s_nssai:
        - sst: 1
          sd: '000001'
"""


@pytest.fixture
def mock_amf_config_with_new_slice():
    """AMF configuration with VR gaming slice added."""
    return """
amf:
  plmn_support:
    - plmn_id:
        mcc: 999
        mnc: 70
      s_nssai:
        - sst: 1
          sd: '000001'
        - sst: 1
          sd: '000002'
"""


@pytest.fixture
def mock_gnb_config():
    """Sample gNB configuration."""
    return """
mcc: 999
mnc: 70
tac: 1
slices:
  - sst: 1
    sd: 0x000001
"""


@pytest.fixture
def mock_gnb_config_with_new_slice():
    """gNB configuration with VR gaming slice added."""
    return """
mcc: 999
mnc: 70
tac: 1
slices:
  - sst: 1
    sd: 0x000001
  - sst: 1
    sd: 0x000002
"""


@pytest.fixture
def mock_smf_config():
    """Sample SMF configuration."""
    return """
smf:
  info:
    - s_nssai:
        - sst: 1
          sd: '000001'
          dnn:
            - internet
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
"""


@pytest.fixture
def mock_smf_config_with_new_slice():
    """SMF configuration with VR gaming slice added."""
    return """
smf:
  info:
    - s_nssai:
        - sst: 1
          sd: '000001'
          dnn:
            - internet
    - s_nssai:
        - sst: 1
          sd: '000002'
          dnn:
            - vr_gaming
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
    - addr: 10.47.0.1/16
      dnn: vr_gaming
"""


@pytest.fixture
def mock_nssf_config():
    """Sample NSSF configuration."""
    return """
nssf:
  nsi:
    - addr: nrf
      port: 7777
      s_nssai:
        sst: 1
        sd: '000001'
"""


@pytest.fixture
def mock_nssf_config_with_new_slice():
    """NSSF configuration with VR gaming slice added."""
    return """
nssf:
  nsi:
    - addr: nrf
      port: 7777
      s_nssai:
        sst: 1
        sd: '000001'
    - addr: nrf
      port: 7777
      s_nssai:
        sst: 1
        sd: '000002'
"""


@pytest.fixture
def mock_upf_config():
    """Sample UPF configuration."""
    return """
upf:
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
"""


@pytest.fixture
def mock_upf_config_with_new_slice():
    """UPF configuration with VR gaming slice added."""
    return """
upf:
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
    - addr: 10.47.0.1/16
      dnn: vr_gaming
"""


@pytest.fixture
def mock_sandbox_responses(
    mock_amf_config,
    mock_gnb_config,
    mock_smf_config,
    mock_nssf_config,
    mock_upf_config,
):
    """Create mock sandbox responses for all NFs."""

    def create_exec_result(stdout: str, success: bool = True):
        result = MagicMock()
        result.success = success
        result.stdout = stdout
        result.stderr = ""
        return result

    sandboxes = {
        "amf": MagicMock(),
        "gnb": MagicMock(),
        "smf": MagicMock(),
        "nssf": MagicMock(),
        "upf": MagicMock(),
        "mongo": MagicMock(),
        "ue": MagicMock(),
    }

    # Configure exec methods as AsyncMock
    for name, sb in sandboxes.items():
        sb.exec = AsyncMock()

    # Set up default responses
    sandboxes["amf"].exec.return_value = create_exec_result(mock_amf_config)
    sandboxes["gnb"].exec.return_value = create_exec_result(mock_gnb_config)
    sandboxes["smf"].exec.return_value = create_exec_result(mock_smf_config)
    sandboxes["nssf"].exec.return_value = create_exec_result(mock_nssf_config)
    sandboxes["upf"].exec.return_value = create_exec_result(mock_upf_config)

    return sandboxes


# =============================================================================
# check_slice_consistency Tests
# =============================================================================


class TestCheckSliceConsistency:
    """Tests for check_slice_consistency tool.

    The tool raises ToolError for failures (invalid params or missing components)
    and returns a success dict when all checks pass.
    """

    @pytest.mark.asyncio
    async def test_check_existing_slice_consistent(self, mock_sandbox_responses):
        """Existing slice (000001) should be consistent and return success dict."""
        # MongoDB returns a subscriber with the slice
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = json.dumps([{"imsi": "999700000000001"}])
        mock_sandbox_responses["mongo"].exec.return_value = mongo_result

        def sandbox_selector(name):
            return mock_sandbox_responses[name]

        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()
            result = await tool_func(sst=1, sd="000001")

        # On success, returns dict with checks_performed and message
        assert "message" in result
        assert result["checks_performed"]["amf_configured"] is True
        assert result["checks_performed"]["smf_configured"] is True
        assert result["checks_performed"]["mongodb_subscriber_exists"] is True

    @pytest.mark.asyncio
    async def test_check_missing_slice_raises_error(self, mock_sandbox_responses):
        """Non-existent slice should raise ToolError with diagnostic info."""
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = "[]"
        mock_sandbox_responses["mongo"].exec.return_value = mongo_result

        def sandbox_selector(name):
            return mock_sandbox_responses[name]

        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=1, sd="000002")

            error_msg = str(exc_info.value)
            assert "SST=1 SD=000002" in error_msg
            assert "BLOCKERS" in error_msg
            assert "amf_configured" in error_msg or "AMF" in error_msg

    @pytest.mark.asyncio
    async def test_check_invalid_sst(self, mock_sandbox_responses):
        """Invalid SST should raise ToolError."""
        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=lambda name: mock_sandbox_responses[name],
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=256, sd="000001")

            assert "Invalid SST" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_invalid_sd(self, mock_sandbox_responses):
        """Invalid SD should raise ToolError."""
        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=lambda name: mock_sandbox_responses[name],
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=1, sd="invalid")

            assert "Invalid SD" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_generates_recommendations(self, mock_sandbox_responses):
        """Error message should include recommended actions."""
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = "[]"
        mock_sandbox_responses["mongo"].exec.return_value = mongo_result

        def sandbox_selector(name):
            return mock_sandbox_responses[name]

        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=1, sd="000002")

            error_msg = str(exc_info.value)
            assert "Recommended Actions" in error_msg
            assert "add_gnb_slice" in error_msg
            assert "add_smf_slice" in error_msg or "AMF" in error_msg


class TestCheckSliceConsistencyFullStack:
    """Tests for complete slice provisioning workflow."""

    @pytest.mark.asyncio
    async def test_full_vr_gaming_slice_after_provisioning(
        self,
        mock_amf_config_with_new_slice,
        mock_gnb_config_with_new_slice,
        mock_smf_config_with_new_slice,
        mock_nssf_config_with_new_slice,
        mock_upf_config_with_new_slice,
    ):
        """After provisioning, VR gaming slice should be consistent and return success."""

        def create_exec_result(stdout: str):
            result = MagicMock()
            result.success = True
            result.stdout = stdout
            result.stderr = ""
            return result

        sandboxes = {
            "amf": MagicMock(),
            "gnb": MagicMock(),
            "smf": MagicMock(),
            "nssf": MagicMock(),
            "upf": MagicMock(),
            "mongo": MagicMock(),
        }

        for sb in sandboxes.values():
            sb.exec = AsyncMock()

        # Configure responses with new slice
        sandboxes["amf"].exec.return_value = create_exec_result(
            mock_amf_config_with_new_slice
        )
        sandboxes["gnb"].exec.return_value = create_exec_result(
            mock_gnb_config_with_new_slice
        )
        sandboxes["smf"].exec.return_value = create_exec_result(
            mock_smf_config_with_new_slice
        )
        sandboxes["nssf"].exec.return_value = create_exec_result(
            mock_nssf_config_with_new_slice
        )
        sandboxes["upf"].exec.return_value = create_exec_result(
            mock_upf_config_with_new_slice
        )
        sandboxes["mongo"].exec.return_value = create_exec_result(
            json.dumps([{"imsi": "999700000000001"}])
        )

        def sandbox_selector(name):
            return sandboxes[name]

        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()
            result = await tool_func(sst=1, sd="000002")

        # On success, the tool returns a dict with checks_performed
        assert "message" in result
        assert result["checks_performed"]["amf_configured"] is True
        assert result["checks_performed"]["gnb_configured"] is True
        assert result["checks_performed"]["smf_configured"] is True
        assert result["checks_performed"]["nssf_configured"] is True
        assert result["checks_performed"]["upf_configured"] is True
        assert result["checks_performed"]["mongodb_subscriber_exists"] is True


# =============================================================================
# test_slice_connectivity Tests
# =============================================================================


class TestSliceConnectivity:
    """Tests for test_slice_connectivity tool.

    The tool raises ToolError for failures and returns a dict on success.
    """

    @pytest.fixture
    def mock_ue_sandbox(self):
        """Create mock UE sandbox."""
        sandbox = MagicMock()
        sandbox.exec = AsyncMock()
        return sandbox

    @pytest.fixture
    def mock_mongo_sandbox(self):
        """Create mock MongoDB sandbox."""
        sandbox = MagicMock()
        sandbox.exec = AsyncMock()
        return sandbox

    @pytest.mark.asyncio
    async def test_connectivity_success(self, mock_ue_sandbox, mock_mongo_sandbox):
        """Successful connectivity test returns success dict."""
        # MongoDB returns subscriber
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = json.dumps({"imsi": "999700000000001"})
        mock_mongo_sandbox.exec.return_value = mongo_result

        # UE status - registered
        status_result = MagicMock()
        status_result.success = True
        status_result.stdout = "cm-state: CM-REGISTERED\nsst: 1\nsd: 000001"

        # IP address
        ip_result = MagicMock()
        ip_result.success = True
        ip_result.stdout = "inet 10.46.0.2/16 scope global uesimtun0"

        # Ping success
        ping_result = MagicMock()
        ping_result.success = True
        ping_result.stdout = """
PING 10.45.0.13 (10.45.0.13) 56(84) bytes of data.
64 bytes from 10.45.0.13: icmp_seq=1 ttl=64 time=5.23 ms
64 bytes from 10.45.0.13: icmp_seq=2 ttl=64 time=4.89 ms

--- 10.45.0.13 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4005ms
rtt min/avg/max/mdev = 4.890/5.100/5.230/0.170 ms
"""

        mock_ue_sandbox.exec.side_effect = [status_result, ip_result, ping_result]

        def sandbox_selector(name):
            if name == "mongo":
                return mock_mongo_sandbox
            return mock_ue_sandbox

        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()
            result = await tool_func(sst=1, sd="000001")

        assert result["connectivity_status"] == "CONNECTED"
        assert result["ue"]["ip_address"] == "10.46.0.2"
        assert result["latency"]["avg_ms"] is not None

    @pytest.mark.asyncio
    async def test_connectivity_no_subscriber(self, mock_ue_sandbox, mock_mongo_sandbox):
        """No subscriber found for slice raises ToolError."""
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = "null"
        mock_mongo_sandbox.exec.return_value = mongo_result

        def sandbox_selector(name):
            if name == "mongo":
                return mock_mongo_sandbox
            return mock_ue_sandbox

        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=1, sd="000099")

            assert "subscriber" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_connectivity_ue_not_registered(
        self, mock_ue_sandbox, mock_mongo_sandbox
    ):
        """UE not registered raises ToolError."""
        # MongoDB returns subscriber
        mongo_result = MagicMock()
        mongo_result.success = True
        mongo_result.stdout = json.dumps({"imsi": "999700000000001"})
        mock_mongo_sandbox.exec.return_value = mongo_result

        # UE status - not registered
        status_result = MagicMock()
        status_result.success = True
        status_result.stdout = "cm-state: CM-IDLE"
        mock_ue_sandbox.exec.return_value = status_result

        def sandbox_selector(name):
            if name == "mongo":
                return mock_mongo_sandbox
            return mock_ue_sandbox

        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=1, sd="000001")

            error_msg = str(exc_info.value).lower()
            assert "not registered" in error_msg or "registration" in error_msg

    @pytest.mark.asyncio
    async def test_connectivity_invalid_sst(self, mock_ue_sandbox, mock_mongo_sandbox):
        """Invalid SST parameter raises ToolError."""
        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=lambda name: mock_mongo_sandbox
            if name == "mongo"
            else mock_ue_sandbox,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()

            with pytest.raises(ToolError) as exc_info:
                await tool_func(sst=-1, sd="000001")

            assert "Invalid SST" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connectivity_with_explicit_imsi(
        self, mock_ue_sandbox, mock_mongo_sandbox
    ):
        """Test with explicit IMSI (skips MongoDB lookup)."""
        # UE status - registered
        status_result = MagicMock()
        status_result.success = True
        status_result.stdout = "cm-state: CM-REGISTERED\nsst: 1\nsd: 000001"

        # IP address
        ip_result = MagicMock()
        ip_result.success = True
        ip_result.stdout = "inet 10.46.0.2/16 scope global uesimtun0"

        # Ping success
        ping_result = MagicMock()
        ping_result.success = True
        ping_result.stdout = """
5 packets transmitted, 5 received, 0% packet loss, time 4005ms
rtt min/avg/max/mdev = 4.890/5.100/5.230/0.170 ms
"""

        mock_ue_sandbox.exec.side_effect = [status_result, ip_result, ping_result]

        def sandbox_selector(name):
            if name == "mongo":
                return mock_mongo_sandbox
            return mock_ue_sandbox

        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()
            result = await tool_func(sst=1, sd="000001", imsi="999700000000001")

        assert result["connectivity_status"] == "CONNECTED"
        # MongoDB should not have been called
        mock_mongo_sandbox.exec.assert_not_called()


# =============================================================================
# Full Workflow Integration Test
# =============================================================================


class TestFullProvisioningWorkflow:
    """Integration tests simulating the full slice provisioning workflow."""

    @pytest.mark.asyncio
    async def test_full_vr_gaming_slice_workflow(self):
        """Test complete VR gaming slice provisioning workflow.

        This test simulates the workflow described in the task specification:
        1. Add subscriber to MongoDB
        2. Configure AMF
        3. Configure gNB
        4. Configure SMF
        5. Configure UPF
        6. Validate consistency
        7. Test connectivity
        """

        def create_exec_result(stdout: str, success: bool = True):
            result = MagicMock()
            result.success = success
            result.stdout = stdout
            result.stderr = ""
            return result

        # Configuration after all components are set up
        final_amf_config = """
amf:
  plmn_support:
    - plmn_id:
        mcc: 999
        mnc: 70
      s_nssai:
        - sst: 1
          sd: '000001'
        - sst: 1
          sd: '000002'
"""

        final_gnb_config = """
mcc: 999
mnc: 70
tac: 1
slices:
  - sst: 1
    sd: 0x000001
  - sst: 1
    sd: 0x000002
"""

        final_smf_config = """
smf:
  info:
    - s_nssai:
        - sst: 1
          sd: '000001'
          dnn:
            - internet
    - s_nssai:
        - sst: 1
          sd: '000002'
          dnn:
            - vr_gaming
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
    - addr: 10.47.0.1/16
      dnn: vr_gaming
"""

        final_nssf_config = """
nssf:
  nsi:
    - addr: nrf
      port: 7777
      s_nssai:
        sst: 1
        sd: '000001'
    - addr: nrf
      port: 7777
      s_nssai:
        sst: 1
        sd: '000002'
"""

        final_upf_config = """
upf:
  subnet:
    - addr: 10.46.0.1/16
      dnn: internet
    - addr: 10.47.0.1/16
      dnn: vr_gaming
"""

        sandboxes = {
            "amf": MagicMock(),
            "gnb": MagicMock(),
            "smf": MagicMock(),
            "nssf": MagicMock(),
            "upf": MagicMock(),
            "mongo": MagicMock(),
            "ue": MagicMock(),
        }

        for sb in sandboxes.values():
            sb.exec = AsyncMock()

        # Set up final configuration responses
        sandboxes["amf"].exec.return_value = create_exec_result(final_amf_config)
        sandboxes["gnb"].exec.return_value = create_exec_result(final_gnb_config)
        sandboxes["smf"].exec.return_value = create_exec_result(final_smf_config)
        sandboxes["nssf"].exec.return_value = create_exec_result(final_nssf_config)
        sandboxes["upf"].exec.return_value = create_exec_result(final_upf_config)
        sandboxes["mongo"].exec.return_value = create_exec_result(
            json.dumps([{"imsi": "999700000000001"}])
        )

        def sandbox_selector(name):
            return sandboxes[name]

        # Step 6: Validate consistency (should succeed and return dict with checks_performed)
        with patch(
            "inspect_5gs_sandbox.tools.validation.check_slice_consistency.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.check_slice_consistency import (
                check_slice_consistency,
            )

            tool_func = check_slice_consistency()
            consistency = await tool_func(sst=1, sd="000002")

        # On success, returns dict with checks_performed
        assert "message" in consistency
        assert consistency["checks_performed"]["amf_configured"] is True
        assert consistency["checks_performed"]["gnb_configured"] is True
        assert consistency["checks_performed"]["smf_configured"] is True
        assert consistency["checks_performed"]["nssf_configured"] is True
        assert consistency["checks_performed"]["upf_configured"] is True
        assert consistency["checks_performed"]["mongodb_subscriber_exists"] is True

        # Step 7: Test connectivity
        status_result = create_exec_result("cm-state: CM-REGISTERED\nsst: 1\nsd: 000002")
        ip_result = create_exec_result("inet 10.47.0.2/16 scope global uesimtun0")
        ping_result = create_exec_result(
            "5 packets transmitted, 5 received, 0% packet loss\n"
            "rtt min/avg/max/mdev = 6.0/8.5/12.0/1.3 ms"
        )

        sandboxes["ue"].exec.side_effect = [status_result, ip_result, ping_result]
        sandboxes["mongo"].exec.return_value = create_exec_result(
            json.dumps({"imsi": "999700000000001"})
        )

        with patch(
            "inspect_5gs_sandbox.tools.validation.test_slice_connectivity.sandbox",
            side_effect=sandbox_selector,
        ):
            from inspect_5gs_sandbox.tools.validation.test_slice_connectivity import (
                test_slice_connectivity,
            )

            tool_func = test_slice_connectivity()
            connectivity = await tool_func(sst=1, sd="000002")

        assert connectivity["connectivity_status"] == "CONNECTED"
        assert connectivity["ue"]["ip_address"] == "10.47.0.2"
        assert connectivity["latency"]["avg_ms"] == 8.5
