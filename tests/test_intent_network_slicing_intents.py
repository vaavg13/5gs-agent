"""Tests for the intent schema helpers in the intent-focused example."""

import sys
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "intent_network_slicing"
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from intents import (
    IntentValidationError,
    build_expected_metrics_from_intent,
    validate_intent,
)


def test_validate_intent_normalizes_slice_and_objectives():
    intent = {
        "service": "vr_gaming",
        "slice": {"sst": 1, "sd": "0x1"},
        "objectives": {
            "hard": [
                {"metric": "uplink_throughput_mbps", "op": ">=", "value": 50},
                {"metric": "latency_ms_p95", "op": "<=", "value": 20},
            ],
            "soft": [
                {"metric": "packet_loss_pct", "op": "<=", "value": 0.1, "weight": 0.5}
            ],
        },
        "control": {"max_actions": 4},
    }

    normalized = validate_intent(intent)

    assert normalized["slice"] == {"sst": 1, "sd": "000001"}
    assert normalized["objectives"]["hard"][1]["metric"] == "max_latency_ms"
    assert normalized["objectives"]["soft"][0]["metric"] == "max_packet_loss_pct"


def test_build_expected_metrics_from_intent_uses_normalized_metric_names():
    intent = {
        "service": "vr_gaming",
        "objectives": {
            "hard": [
                {"metric": "latency_ms_avg", "op": "<=", "value": 18},
            ],
            "soft": [
                {"metric": "downlink_throughput_mbps", "op": ">=", "value": 100, "weight": 0.2}
            ],
        },
    }

    expected = build_expected_metrics_from_intent(intent)

    assert expected["max_latency_ms"] == 18.0
    assert expected["downlink_throughput_mbps"] == 100.0


def test_build_expected_metrics_from_intent_keeps_ue_qualified_metric_names():
    intent = {
        "service": "vr_gaming",
        "ues": [
            {"ue_id": "ue_premium", "service": "ue_premium", "role": "target"},
        ],
        "objectives": {
            "hard": [
                {"metric": "ue_premium.latency_ms_p95", "op": "<=", "value": 20},
            ],
        },
    }

    expected = build_expected_metrics_from_intent(intent)

    assert expected["ue_premium.max_latency_ms"] == 20.0


def test_validate_intent_rejects_wrong_operator():
    intent = {
        "service": "vr_gaming",
        "objectives": {
            "hard": [
                {"metric": "max_latency_ms", "op": ">=", "value": 20},
            ]
        },
    }

    try:
        validate_intent(intent)
    except IntentValidationError as exc:
        assert "requires operator '<='" in str(exc)
    else:
        raise AssertionError("Expected IntentValidationError")
