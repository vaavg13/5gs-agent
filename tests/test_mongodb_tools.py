"""Unit tests for MongoDB tools.

These tests validate the MongoDB tools for Open5GS subscriber management
using mocked sandbox operations.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from inspect_5gs_sandbox.tools.mongodb._validators import (
    build_response,
    validate_arp_priority,
    validate_dnn,
    validate_imsi,
    validate_k_opc,
    validate_qos_index,
    validate_sd,
    validate_sst,
)


# =============================================================================
# Validator Tests
# =============================================================================


class TestValidateImsi:
    """Tests for IMSI validation."""

    def test_valid_imsi(self):
        """Valid 15-digit IMSI passes validation."""
        valid, clean, error = validate_imsi("999700000000001")
        assert valid is True
        assert clean == "999700000000001"
        assert error == ""

    def test_valid_imsi_with_prefix(self):
        """IMSI with 'imsi-' prefix is normalized."""
        valid, clean, error = validate_imsi("imsi-999700000000001")
        assert valid is True
        assert clean == "999700000000001"
        assert error == ""

    def test_invalid_imsi_too_short(self):
        """IMSI with fewer than 15 digits fails validation."""
        valid, clean, error = validate_imsi("99970000000")
        assert valid is False
        assert "15 digits" in error

    def test_invalid_imsi_too_long(self):
        """IMSI with more than 15 digits fails validation."""
        valid, clean, error = validate_imsi("9997000000000012345")
        assert valid is False
        assert "15 digits" in error

    def test_invalid_imsi_non_numeric(self):
        """IMSI with non-numeric characters fails validation."""
        valid, clean, error = validate_imsi("99970000000abc1")
        assert valid is False
        assert "15 digits" in error


class TestValidateSst:
    """Tests for SST validation."""

    def test_valid_sst_integer(self):
        """Valid SST integer passes validation."""
        valid, sst, error = validate_sst(1)
        assert valid is True
        assert sst == 1
        assert error == ""

    def test_valid_sst_string(self):
        """Valid SST as string is converted to integer."""
        valid, sst, error = validate_sst("128")
        assert valid is True
        assert sst == 128
        assert error == ""

    def test_valid_sst_boundary_low(self):
        """SST at lower boundary (0) passes validation."""
        valid, sst, error = validate_sst(0)
        assert valid is True
        assert sst == 0

    def test_valid_sst_boundary_high(self):
        """SST at upper boundary (255) passes validation."""
        valid, sst, error = validate_sst(255)
        assert valid is True
        assert sst == 255

    def test_invalid_sst_negative(self):
        """Negative SST fails validation."""
        valid, sst, error = validate_sst(-1)
        assert valid is False
        assert "between 0 and 255" in error

    def test_invalid_sst_too_high(self):
        """SST > 255 fails validation."""
        valid, sst, error = validate_sst(256)
        assert valid is False
        assert "between 0 and 255" in error

    def test_invalid_sst_non_numeric(self):
        """Non-numeric SST fails validation."""
        valid, sst, error = validate_sst("abc")
        assert valid is False
        assert "integer" in error


class TestValidateSd:
    """Tests for SD (Slice Differentiator) validation."""

    def test_valid_sd_hex_string(self):
        """Valid 6-char hex string passes validation."""
        valid, sd, error = validate_sd("000001")
        assert valid is True
        assert sd == "000001"
        assert error == ""

    def test_valid_sd_uppercase(self):
        """Uppercase hex is normalized to lowercase."""
        valid, sd, error = validate_sd("AABBCC")
        assert valid is True
        assert sd == "aabbcc"

    def test_valid_sd_with_0x_prefix(self):
        """SD with 0x prefix is normalized."""
        valid, sd, error = validate_sd("0x000001")
        assert valid is True
        assert sd == "000001"

    def test_valid_sd_short_string_padded(self):
        """Short SD string is padded with zeros."""
        valid, sd, error = validate_sd("1")
        assert valid is True
        assert sd == "000001"

    def test_valid_sd_integer(self):
        """Integer SD is converted to hex string."""
        valid, sd, error = validate_sd(1)
        assert valid is True
        assert sd == "000001"

    def test_valid_sd_integer_larger(self):
        """Larger integer SD is converted correctly."""
        valid, sd, error = validate_sd(256)
        assert valid is True
        assert sd == "000100"

    def test_invalid_sd_non_hex(self):
        """Non-hex characters fail validation."""
        valid, sd, error = validate_sd("00000g")
        assert valid is False
        assert "hex" in error.lower()

    def test_invalid_sd_integer_too_large(self):
        """Integer SD > 0xFFFFFF fails validation."""
        valid, sd, error = validate_sd(0x1000000)
        assert valid is False
        assert "16777215" in error


class TestValidateQosIndex:
    """Tests for QoS index (5QI) validation."""

    def test_valid_qos_index(self):
        """Valid QoS index passes validation."""
        valid, qos, error = validate_qos_index(9)
        assert valid is True
        assert qos == 9

    def test_valid_qos_index_boundary(self):
        """QoS index at boundaries passes validation."""
        valid, qos, error = validate_qos_index(0)
        assert valid is True
        assert qos == 0

        valid, qos, error = validate_qos_index(255)
        assert valid is True
        assert qos == 255

    def test_invalid_qos_index_negative(self):
        """Negative QoS index fails validation."""
        valid, qos, error = validate_qos_index(-1)
        assert valid is False
        assert "between 0 and 255" in error

    def test_invalid_qos_index_too_high(self):
        """QoS index > 255 fails validation."""
        valid, qos, error = validate_qos_index(256)
        assert valid is False
        assert "between 0 and 255" in error


class TestValidateArpPriority:
    """Tests for ARP priority validation."""

    def test_valid_arp_priority(self):
        """Valid ARP priority passes validation."""
        valid, arp, error = validate_arp_priority(8)
        assert valid is True
        assert arp == 8

    def test_valid_arp_priority_boundaries(self):
        """ARP priority at boundaries passes validation."""
        valid, arp, error = validate_arp_priority(1)
        assert valid is True
        assert arp == 1

        valid, arp, error = validate_arp_priority(15)
        assert valid is True
        assert arp == 15

    def test_invalid_arp_priority_zero(self):
        """ARP priority of 0 fails validation."""
        valid, arp, error = validate_arp_priority(0)
        assert valid is False
        assert "between 1 and 15" in error

    def test_invalid_arp_priority_too_high(self):
        """ARP priority > 15 fails validation."""
        valid, arp, error = validate_arp_priority(16)
        assert valid is False
        assert "between 1 and 15" in error


class TestValidateKOpc:
    """Tests for K and OPc key validation."""

    def test_valid_keys(self):
        """Valid 32-char hex keys pass validation."""
        k = "465B5CE8B199B49FAA5F0A2EE238A6BC"
        opc = "E8ED289DEBA952E4283B54E88E6183CA"
        valid, k_upper, error = validate_k_opc(k, opc)
        assert valid is True
        assert k_upper == k.upper()

    def test_invalid_k_too_short(self):
        """K key with fewer than 32 characters fails validation."""
        valid, _, error = validate_k_opc("465B5CE8B199B49F", "E8ED289DEBA952E4283B54E88E6183CA")
        assert valid is False
        assert "32 hex" in error

    def test_invalid_opc_non_hex(self):
        """OPc key with non-hex characters fails validation."""
        valid, _, error = validate_k_opc(
            "465B5CE8B199B49FAA5F0A2EE238A6BC",
            "E8ED289DEBA952E4283B54E88E6183GG"  # GG is not hex
        )
        assert valid is False
        assert "OPc" in error


class TestValidateDnn:
    """Tests for DNN validation."""

    def test_valid_dnn(self):
        """Valid DNN passes validation."""
        valid, dnn, error = validate_dnn("internet")
        assert valid is True
        assert dnn == "internet"

    def test_valid_dnn_with_dots(self):
        """DNN with dots passes validation."""
        valid, dnn, error = validate_dnn("ims.mnc001.mcc999.3gppnetwork.org")
        assert valid is True

    def test_invalid_dnn_empty(self):
        """Empty DNN fails validation."""
        valid, dnn, error = validate_dnn("")
        assert valid is False
        assert "empty" in error.lower()

    def test_invalid_dnn_special_chars(self):
        """DNN with invalid special characters fails validation."""
        valid, dnn, error = validate_dnn("inter net!")
        assert valid is False
        assert "invalid characters" in error.lower()


class TestBuildResponse:
    """Tests for the response builder utility."""

    def test_success_response(self):
        """Success response has correct structure."""
        response = build_response(status="success", data={"imsi": "123"})
        assert response["status"] == "success"
        assert response["data"]["imsi"] == "123"
        assert "error" not in response

    def test_error_response(self):
        """Error response has correct structure."""
        response = build_response(status="error", error="Something went wrong")
        assert response["status"] == "error"
        assert response["error"] == "Something went wrong"
        assert "data" not in response

    def test_response_with_warnings(self):
        """Response can include warnings."""
        response = build_response(
            status="success",
            data={"imsi": "123"},
            warnings=["Value was normalized"]
        )
        assert response["status"] == "success"
        assert response["warnings"] == ["Value was normalized"]


# =============================================================================
# Tool Execution Tests (Mocked)
# =============================================================================


@pytest.fixture
def mock_mongo_sandbox():
    """Create a mock mongo sandbox."""
    mock_sandbox = MagicMock()
    mock_sandbox.exec = AsyncMock()
    return mock_sandbox


@pytest.fixture
def sample_subscriber_doc():
    """Sample subscriber document from MongoDB."""
    return {
        "_id": {"$oid": "abc123"},
        "imsi": "999700000000001",
        "security": {
            "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
            "amf": "8000",
            "op": None,
            "opc": "E8ED289DEBA952E4283B54E88E6183CA"
        },
        "ambr": {
            "downlink": {"value": 1, "unit": 3},
            "uplink": {"value": 1, "unit": 3}
        },
        "slice": [
            {
                "sst": 1,
                "sd": "000001",
                "default_indicator": True,
                "session": [
                    {
                        "name": "internet",
                        "type": 3,
                        "dnn": "internet",
                        "qos": {
                            "index": 9,
                            "arp": {
                                "priority_level": 8,
                                "pre_emption_capability": 1,
                                "pre_emption_vulnerability": 1
                            }
                        },
                        "ambr": {
                            "downlink": {"value": 1, "unit": 3},
                            "uplink": {"value": 1, "unit": 3}
                        }
                    }
                ]
            }
        ]
    }


class TestGetSubscriberFromMongodb:
    """Tests for get_subscriber_from_mongodb tool."""

    @pytest.mark.asyncio
    async def test_get_subscriber_success(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Successfully retrieves subscriber from MongoDB."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = json.dumps(sample_subscriber_doc)
        mock_mongo_sandbox.exec.return_value = mock_result

        with patch("inspect_5gs_sandbox.tools.mongodb.get_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.get_subscriber import get_subscriber_from_mongodb
            tool_func = get_subscriber_from_mongodb()
            result = await tool_func("999700000000001")

        assert result["status"] == "success"
        assert result["data"]["imsi"] == "999700000000001"
        assert "subscriber" in result["data"]

    @pytest.mark.asyncio
    async def test_get_subscriber_not_found(self, mock_mongo_sandbox):
        """Returns error when subscriber not found."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = "null"
        mock_mongo_sandbox.exec.return_value = mock_result

        with patch("inspect_5gs_sandbox.tools.mongodb.get_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.get_subscriber import get_subscriber_from_mongodb
            tool_func = get_subscriber_from_mongodb()
            result = await tool_func("999700000000099")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_subscriber_invalid_imsi(self, mock_mongo_sandbox):
        """Returns error for invalid IMSI format."""
        with patch("inspect_5gs_sandbox.tools.mongodb.get_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.get_subscriber import get_subscriber_from_mongodb
            tool_func = get_subscriber_from_mongodb()
            result = await tool_func("invalid")

        assert result["status"] == "error"
        assert "15 digits" in result["error"]

    @pytest.mark.asyncio
    async def test_get_subscriber_connection_error(self, mock_mongo_sandbox):
        """Returns error on MongoDB connection failure."""
        mock_mongo_sandbox.exec.side_effect = Exception("Connection refused")

        with patch("inspect_5gs_sandbox.tools.mongodb.get_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.get_subscriber import get_subscriber_from_mongodb
            tool_func = get_subscriber_from_mongodb()
            result = await tool_func("999700000000001")

        assert result["status"] == "error"
        assert "connection error" in result["error"].lower()


class TestAddSubscriberToMongodb:
    """Tests for add_subscriber_to_mongodb tool."""

    @pytest.mark.asyncio
    async def test_add_subscriber_success(self, mock_mongo_sandbox):
        """Successfully adds new subscriber."""
        # First call: check if subscriber exists (not found)
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = "null"

        # Second call: insert subscriber
        insert_result = MagicMock()
        insert_result.success = True
        insert_result.stdout = json.dumps({"insertedId": "new_id_123"})

        mock_mongo_sandbox.exec.side_effect = [check_result, insert_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.add_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_subscriber import add_subscriber_to_mongodb
            tool_func = add_subscriber_to_mongodb()
            result = await tool_func(
                imsi="999700000000002",
                k="465B5CE8B199B49FAA5F0A2EE238A6BC",
                opc="E8ED289DEBA952E4283B54E88E6183CA",
                sst=1,
                sd="000001",
                dnn="internet",
            )

        assert result["status"] == "success"
        assert result["data"]["imsi"] == "999700000000002"
        assert result["data"]["inserted_id"] == "new_id_123"

    @pytest.mark.asyncio
    async def test_add_subscriber_already_exists(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Returns error when subscriber already exists."""
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)

        mock_mongo_sandbox.exec.return_value = check_result

        with patch("inspect_5gs_sandbox.tools.mongodb.add_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_subscriber import add_subscriber_to_mongodb
            tool_func = add_subscriber_to_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                k="465B5CE8B199B49FAA5F0A2EE238A6BC",
                opc="E8ED289DEBA952E4283B54E88E6183CA",
                sst=1,
                sd="000001",
                dnn="internet",
            )

        assert result["status"] == "error"
        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_add_subscriber_invalid_k(self, mock_mongo_sandbox):
        """Returns error for invalid K key."""
        with patch("inspect_5gs_sandbox.tools.mongodb.add_subscriber.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_subscriber import add_subscriber_to_mongodb
            tool_func = add_subscriber_to_mongodb()
            result = await tool_func(
                imsi="999700000000002",
                k="invalid_key",
                opc="E8ED289DEBA952E4283B54E88E6183CA",
                sst=1,
                sd="000001",
                dnn="internet",
            )

        assert result["status"] == "error"
        assert "32 hex" in result["error"]


class TestAddSliceToSubscriberMongodb:
    """Tests for add_slice_to_subscriber_mongodb tool."""

    @pytest.mark.asyncio
    async def test_add_slice_success(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Successfully adds new slice to subscriber."""
        # First call: find subscriber
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)

        # Second call: update subscriber
        update_result = MagicMock()
        update_result.success = True
        update_result.stdout = json.dumps({"modifiedCount": 1})

        mock_mongo_sandbox.exec.side_effect = [check_result, update_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.add_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_slice import add_slice_to_subscriber_mongodb
            tool_func = add_slice_to_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000002",  # Different SD
                dnn="vr_gaming",
                ambr_uplink=1,
                ambr_downlink=1,
            )

        assert result["status"] == "success"
        assert result["data"]["slice_added"]["sst"] == 1
        assert result["data"]["slice_added"]["sd"] == "000002"

    @pytest.mark.asyncio
    async def test_add_slice_subscriber_not_found(self, mock_mongo_sandbox):
        """Returns error when subscriber not found."""
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = "null"

        mock_mongo_sandbox.exec.return_value = check_result

        with patch("inspect_5gs_sandbox.tools.mongodb.add_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_slice import add_slice_to_subscriber_mongodb
            tool_func = add_slice_to_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000099",
                sst=1,
                sd="000002",
                dnn="vr_gaming",
                ambr_uplink=1,
                ambr_downlink=1,
            )

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_add_slice_already_exists(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Returns error when slice with same sst/sd already exists."""
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)

        mock_mongo_sandbox.exec.return_value = check_result

        with patch("inspect_5gs_sandbox.tools.mongodb.add_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.add_slice import add_slice_to_subscriber_mongodb
            tool_func = add_slice_to_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000001",  # Same as existing slice
                dnn="internet",
                ambr_uplink=1,
                ambr_downlink=1,
            )

        assert result["status"] == "error"
        assert "already exists" in result["error"]


class TestModifySubscriberQosMongodb:
    """Tests for modify_subscriber_qos_mongodb tool."""

    @pytest.mark.asyncio
    async def test_modify_qos_success(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Successfully modifies QoS settings."""
        # First call: find subscriber
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)

        # Second call: update subscriber
        update_result = MagicMock()
        update_result.success = True
        update_result.stdout = json.dumps({"modifiedCount": 1})

        mock_mongo_sandbox.exec.side_effect = [check_result, update_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.modify_qos.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.modify_qos import modify_subscriber_qos_mongodb
            tool_func = modify_subscriber_qos_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000001",
                qos_index=2,
                arp_priority=1,
                ambr_uplink=10,
                ambr_downlink=20,
            )

        assert result["status"] == "success"
        assert result["data"]["new_qos"]["qos_index"] == 2
        assert result["data"]["new_qos"]["arp_priority"] == 1

    @pytest.mark.asyncio
    async def test_modify_qos_slice_not_found(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Returns error when specified slice not found."""
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)

        mock_mongo_sandbox.exec.return_value = check_result

        with patch("inspect_5gs_sandbox.tools.mongodb.modify_qos.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.modify_qos import modify_subscriber_qos_mongodb
            tool_func = modify_subscriber_qos_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000099",  # Non-existent SD
                qos_index=2,
                arp_priority=1,
                ambr_uplink=10,
                ambr_downlink=20,
            )

        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestRemoveSliceFromSubscriberMongodb:
    """Tests for remove_slice_from_subscriber_mongodb tool."""

    @pytest.mark.asyncio
    async def test_remove_slice_success(self, mock_mongo_sandbox):
        """Successfully removes slice from subscriber."""
        # Subscriber with two slices
        subscriber_doc = {
            "imsi": "999700000000001",
            "slice": [
                {"sst": 1, "sd": "000001", "default_indicator": True, "session": [{"dnn": "internet"}]},
                {"sst": 1, "sd": "000002", "default_indicator": False, "session": [{"dnn": "vr_gaming"}]},
            ]
        }

        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(subscriber_doc)

        update_result = MagicMock()
        update_result.success = True
        update_result.stdout = json.dumps({"modifiedCount": 1})

        mock_mongo_sandbox.exec.side_effect = [check_result, update_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.remove_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.remove_slice import remove_slice_from_subscriber_mongodb
            tool_func = remove_slice_from_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000002",
            )

        assert result["status"] == "success"
        assert result["data"]["remaining_slices"] == 1

    @pytest.mark.asyncio
    async def test_remove_slice_last_slice_error(self, mock_mongo_sandbox, sample_subscriber_doc):
        """Returns error when trying to remove last slice."""
        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(sample_subscriber_doc)  # Only has one slice

        mock_mongo_sandbox.exec.return_value = check_result

        with patch("inspect_5gs_sandbox.tools.mongodb.remove_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.remove_slice import remove_slice_from_subscriber_mongodb
            tool_func = remove_slice_from_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000001",
            )

        assert result["status"] == "error"
        assert "last slice" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_remove_slice_warns_on_default(self, mock_mongo_sandbox):
        """Warns when removing default slice."""
        subscriber_doc = {
            "imsi": "999700000000001",
            "slice": [
                {"sst": 1, "sd": "000001", "default_indicator": True, "session": [{"dnn": "internet"}]},
                {"sst": 1, "sd": "000002", "default_indicator": False, "session": [{"dnn": "vr_gaming"}]},
            ]
        }

        check_result = MagicMock()
        check_result.success = True
        check_result.stdout = json.dumps(subscriber_doc)

        update_result = MagicMock()
        update_result.success = True
        update_result.stdout = json.dumps({"modifiedCount": 1})

        mock_mongo_sandbox.exec.side_effect = [check_result, update_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.remove_slice.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.remove_slice import remove_slice_from_subscriber_mongodb
            tool_func = remove_slice_from_subscriber_mongodb()
            result = await tool_func(
                imsi="999700000000001",
                sst=1,
                sd="000001",  # Default slice
            )

        assert result["status"] == "success"
        assert result["warnings"] is not None
        assert any("default" in w.lower() for w in result["warnings"])


class TestListAllSubscribersMongodb:
    """Tests for list_all_subscribers_mongodb tool."""

    @pytest.mark.asyncio
    async def test_list_subscribers_success(self, mock_mongo_sandbox):
        """Successfully lists subscribers."""
        # Count result
        count_result = MagicMock()
        count_result.success = True
        count_result.stdout = "2"

        # List result
        subscribers = [
            {"imsi": "999700000000001", "slice": [{"sst": 1, "sd": "000001", "session": [{"dnn": "internet"}]}]},
            {"imsi": "999700000000002", "slice": [{"sst": 1, "sd": "000002", "session": [{"dnn": "vr_gaming"}]}]},
        ]
        list_result = MagicMock()
        list_result.success = True
        list_result.stdout = json.dumps(subscribers)

        mock_mongo_sandbox.exec.side_effect = [count_result, list_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.list_subscribers.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.list_subscribers import list_all_subscribers_mongodb
            tool_func = list_all_subscribers_mongodb()
            result = await tool_func()

        assert result["status"] == "success"
        assert result["data"]["count"] == 2
        assert result["data"]["total_count"] == 2
        assert len(result["data"]["subscribers"]) == 2

    @pytest.mark.asyncio
    async def test_list_subscribers_empty(self, mock_mongo_sandbox):
        """Returns empty list when no subscribers."""
        count_result = MagicMock()
        count_result.success = True
        count_result.stdout = "0"

        list_result = MagicMock()
        list_result.success = True
        list_result.stdout = "[]"

        mock_mongo_sandbox.exec.side_effect = [count_result, list_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.list_subscribers.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.list_subscribers import list_all_subscribers_mongodb
            tool_func = list_all_subscribers_mongodb()
            result = await tool_func()

        assert result["status"] == "success"
        assert result["data"]["count"] == 0
        assert result["data"]["subscribers"] == []

    @pytest.mark.asyncio
    async def test_list_subscribers_pagination(self, mock_mongo_sandbox):
        """Handles pagination correctly."""
        count_result = MagicMock()
        count_result.success = True
        count_result.stdout = "150"

        subscribers = [
            {"imsi": f"9997000000000{i:02d}", "slice": [{"sst": 1, "sd": "000001", "session": [{"dnn": "internet"}]}]}
            for i in range(50)
        ]
        list_result = MagicMock()
        list_result.success = True
        list_result.stdout = json.dumps(subscribers)

        mock_mongo_sandbox.exec.side_effect = [count_result, list_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.list_subscribers.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.list_subscribers import list_all_subscribers_mongodb
            tool_func = list_all_subscribers_mongodb()
            result = await tool_func(limit=50, offset=50)

        assert result["status"] == "success"
        assert result["data"]["offset"] == 50
        assert result["data"]["limit"] == 50
        assert result["data"]["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_subscribers_limit_capped(self, mock_mongo_sandbox):
        """Caps limit at 1000."""
        count_result = MagicMock()
        count_result.success = True
        count_result.stdout = "5000"

        list_result = MagicMock()
        list_result.success = True
        list_result.stdout = "[]"

        mock_mongo_sandbox.exec.side_effect = [count_result, list_result]

        with patch("inspect_5gs_sandbox.tools.mongodb.list_subscribers.sandbox", return_value=mock_mongo_sandbox):
            from inspect_5gs_sandbox.tools.mongodb.list_subscribers import list_all_subscribers_mongodb
            tool_func = list_all_subscribers_mongodb()
            result = await tool_func(limit=2000)

        assert result["status"] == "success"
        assert result["data"]["limit"] == 1000
        assert result["warnings"] is not None
        assert any("capped" in w.lower() for w in result["warnings"])
