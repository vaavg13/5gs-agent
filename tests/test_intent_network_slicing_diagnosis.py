"""Tests for pure diagnosis inference helpers."""

import sys
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "intent_network_slicing"
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from diagnosis import infer_root_causes


def test_infer_root_causes_prefers_transport_impairment_when_tc_is_active():
    snapshot = {
        "expected_slice": {"sst": 1, "sd": "000001"},
        "ue": {"pdu_session_active": True},
        "upf": {"transport_impairment_detected": True, "qdisc_output": "qdisc netem"},
        "amf": {"configured_slices": [{"sst": 1, "sd": "000001"}]},
        "subscriber": {"records": [{"sst": 1, "sd": "000001"}]},
        "nrf": {"query_success": True},
    }

    hypotheses = infer_root_causes(snapshot)

    assert hypotheses[0]["label"] == "transport_impairment_upf"


def test_infer_root_causes_detects_slice_mismatch():
    snapshot = {
        "expected_slice": {"sst": 1, "sd": "000002"},
        "ue": {"pdu_session_active": True},
        "upf": {"transport_impairment_detected": False, "qdisc_output": ""},
        "amf": {"configured_slices": [{"sst": 1, "sd": "000001"}]},
        "subscriber": {"records": [{"sst": 1, "sd": "000001"}]},
        "nrf": {"query_success": True},
    }

    labels = [item["label"] for item in infer_root_causes(snapshot)]

    assert "slice_config_mismatch" in labels
    assert "subscriber_profile_mismatch" in labels
