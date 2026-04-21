"""Unit tests for mock network metrics generator.

This test suite verifies the mock network metrics generators used for testing
when the UERANSIM infrastructure is non-functional (TEID bug).

Coverage areas:
- Return types and basic contracts
- Seed reproducibility
- Min/max boundary enforcement
- Variance parameter effects
- Statistical properties (mean near target)
- Pass probability affects outcomes
- All metrics present in composite function
"""

import pytest
import statistics
from inspect_5gs_sandbox.scorers.mock_network_metrics import (
    generate_mock_throughput,
    generate_mock_latency,
    generate_mock_jitter,
    generate_mock_packet_loss,
    generate_vr_gaming_measurements,
)


class TestMockThroughput:
    """Test suite for generate_mock_throughput()."""

    def test_returns_float(self):
        """Verify function returns a float value."""
        result = generate_mock_throughput(1000)
        assert isinstance(result, float)

    def test_seed_reproducibility(self):
        """Same seed should produce identical results."""
        result1 = generate_mock_throughput(1000, seed=42)
        result2 = generate_mock_throughput(1000, seed=42)
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different results (with high probability)."""
        result1 = generate_mock_throughput(1000, seed=42)
        result2 = generate_mock_throughput(1000, seed=43)
        assert result1 != result2

    def test_respects_min_value(self):
        """All samples should be >= min_mbps."""
        samples = [
            generate_mock_throughput(1000, min_mbps=500, seed=i)
            for i in range(100)
        ]
        assert all(s >= 500 for s in samples)

    def test_variance_affects_spread(self):
        """Higher variance should produce more spread in values."""
        low_var = [
            generate_mock_throughput(1000, variance_pct=5, seed=i)
            for i in range(100)
        ]
        high_var = [
            generate_mock_throughput(1000, variance_pct=20, seed=i)
            for i in range(100)
        ]
        assert statistics.stdev(low_var) < statistics.stdev(high_var)

    def test_mean_near_target(self):
        """Sample mean should be close to target value (within 10%)."""
        samples = [
            generate_mock_throughput(1000, variance_pct=10, seed=i)
            for i in range(1000)
        ]
        mean = statistics.mean(samples)
        # Allow 10% deviation from target due to sampling variance
        assert 900 <= mean <= 1100

    def test_min_clamp_prevents_negative(self):
        """Verify min_mbps prevents negative values from Gaussian tail."""
        samples = [
            generate_mock_throughput(10, variance_pct=100, min_mbps=0, seed=i)
            for i in range(100)
        ]
        assert all(s >= 0 for s in samples)


class TestMockLatency:
    """Test suite for generate_mock_latency()."""

    def test_returns_float(self):
        """Verify function returns a float value."""
        result = generate_mock_latency(10.0)
        assert isinstance(result, float)

    def test_seed_reproducibility(self):
        """Same seed should produce identical results."""
        result1 = generate_mock_latency(10.0, seed=42)
        result2 = generate_mock_latency(10.0, seed=42)
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different results (with high probability)."""
        result1 = generate_mock_latency(10.0, seed=42)
        result2 = generate_mock_latency(10.0, seed=43)
        assert result1 != result2

    def test_respects_min_value(self):
        """All samples should be >= min_ms."""
        samples = [
            generate_mock_latency(10.0, min_ms=1.0, seed=i)
            for i in range(100)
        ]
        assert all(s >= 1.0 for s in samples)

    def test_variance_affects_spread(self):
        """Higher variance should produce more spread in values."""
        low_var = [
            generate_mock_latency(10.0, variance_pct=10, seed=i)
            for i in range(100)
        ]
        high_var = [
            generate_mock_latency(10.0, variance_pct=30, seed=i)
            for i in range(100)
        ]
        assert statistics.stdev(low_var) < statistics.stdev(high_var)

    def test_mean_near_target(self):
        """Sample mean should be close to target value (within 20%)."""
        samples = [
            generate_mock_latency(10.0, variance_pct=20, seed=i)
            for i in range(1000)
        ]
        mean = statistics.mean(samples)
        # Allow 20% deviation from target due to sampling variance
        assert 8.0 <= mean <= 12.0

    def test_default_min_prevents_zero(self):
        """Verify default min_ms=0.1 prevents unrealistic zero latency."""
        samples = [
            generate_mock_latency(0.5, variance_pct=100, seed=i)
            for i in range(100)
        ]
        assert all(s >= 0.1 for s in samples)


class TestMockJitter:
    """Test suite for generate_mock_jitter()."""

    def test_returns_float(self):
        """Verify function returns a float value."""
        result = generate_mock_jitter(2.0)
        assert isinstance(result, float)

    def test_seed_reproducibility(self):
        """Same seed should produce identical results."""
        result1 = generate_mock_jitter(2.0, seed=42)
        result2 = generate_mock_jitter(2.0, seed=42)
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different results (with high probability)."""
        result1 = generate_mock_jitter(2.0, seed=42)
        result2 = generate_mock_jitter(2.0, seed=43)
        assert result1 != result2

    def test_respects_min_value(self):
        """All samples should be >= min_ms."""
        samples = [
            generate_mock_jitter(2.0, min_ms=0.5, seed=i)
            for i in range(100)
        ]
        assert all(s >= 0.5 for s in samples)

    def test_variance_affects_spread(self):
        """Higher variance should produce more spread in values."""
        low_var = [
            generate_mock_jitter(2.0, variance_pct=15, seed=i)
            for i in range(100)
        ]
        high_var = [
            generate_mock_jitter(2.0, variance_pct=35, seed=i)
            for i in range(100)
        ]
        assert statistics.stdev(low_var) < statistics.stdev(high_var)

    def test_mean_near_target(self):
        """Sample mean should be close to target value (within 25%)."""
        samples = [
            generate_mock_jitter(2.0, variance_pct=25, seed=i)
            for i in range(1000)
        ]
        mean = statistics.mean(samples)
        # Allow 25% deviation from target due to sampling variance
        assert 1.5 <= mean <= 2.5

    def test_default_min_prevents_zero(self):
        """Verify default min_ms=0.1 prevents unrealistic zero jitter."""
        samples = [
            generate_mock_jitter(0.3, variance_pct=100, seed=i)
            for i in range(100)
        ]
        assert all(s >= 0.1 for s in samples)


class TestMockPacketLoss:
    """Test suite for generate_mock_packet_loss()."""

    def test_returns_float(self):
        """Verify function returns a float value."""
        result = generate_mock_packet_loss(0.01)
        assert isinstance(result, float)

    def test_seed_reproducibility(self):
        """Same seed should produce identical results."""
        result1 = generate_mock_packet_loss(0.01, seed=42)
        result2 = generate_mock_packet_loss(0.01, seed=42)
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different results (with high probability)."""
        result1 = generate_mock_packet_loss(0.01, seed=42)
        result2 = generate_mock_packet_loss(0.01, seed=43)
        assert result1 != result2

    def test_respects_min_value(self):
        """All samples should be >= min_pct."""
        samples = [
            generate_mock_packet_loss(0.01, min_pct=0.0, seed=i)
            for i in range(100)
        ]
        assert all(s >= 0.0 for s in samples)

    def test_respects_max_value(self):
        """All samples should be <= max_pct."""
        samples = [
            generate_mock_packet_loss(50.0, variance_pct=100, max_pct=100.0, seed=i)
            for i in range(100)
        ]
        assert all(s <= 100.0 for s in samples)

    def test_variance_affects_spread(self):
        """Higher variance should produce more spread in values."""
        low_var = [
            generate_mock_packet_loss(1.0, variance_pct=25, seed=i)
            for i in range(100)
        ]
        high_var = [
            generate_mock_packet_loss(1.0, variance_pct=75, seed=i)
            for i in range(100)
        ]
        assert statistics.stdev(low_var) < statistics.stdev(high_var)

    def test_mean_near_target(self):
        """Sample mean should be close to target value (within 50%)."""
        samples = [
            generate_mock_packet_loss(1.0, variance_pct=50, seed=i)
            for i in range(1000)
        ]
        mean = statistics.mean(samples)
        # Allow 50% deviation from target due to high default variance
        assert 0.5 <= mean <= 1.5

    def test_clamping_both_bounds(self):
        """Verify both min and max bounds are enforced simultaneously."""
        samples = [
            generate_mock_packet_loss(
                50.0, variance_pct=100, min_pct=10.0, max_pct=90.0, seed=i
            )
            for i in range(100)
        ]
        assert all(10.0 <= s <= 90.0 for s in samples)


class TestVRGamingMeasurements:
    """Test suite for generate_vr_gaming_measurements()."""

    def test_returns_dict(self):
        """Verify function returns a dictionary."""
        result = generate_vr_gaming_measurements()
        assert isinstance(result, dict)

    def test_all_metrics_present(self):
        """Verify all required metrics are in the result."""
        result = generate_vr_gaming_measurements(seed=42)
        expected_keys = {
            "uplink_mbps",
            "downlink_mbps",
            "latency_ms",
            "jitter_ms",
            "packet_loss_pct",
        }
        assert set(result.keys()) == expected_keys

    def test_all_values_are_floats(self):
        """Verify all metric values are floats."""
        result = generate_vr_gaming_measurements(seed=42)
        assert all(isinstance(v, float) for v in result.values())

    def test_seed_reproducibility(self):
        """Same seed should produce identical measurements."""
        result1 = generate_vr_gaming_measurements(seed=42)
        result2 = generate_vr_gaming_measurements(seed=42)
        assert result1 == result2

    def test_different_seeds_different_results(self):
        """Different seeds should produce different measurements."""
        result1 = generate_vr_gaming_measurements(seed=42)
        result2 = generate_vr_gaming_measurements(seed=43)
        # At least one metric should differ
        assert any(result1[k] != result2[k] for k in result1.keys())

    def test_pass_probability_affects_outcomes(self):
        """Higher pass_probability should result in more passing metrics."""
        # SLA thresholds
        THRESHOLDS = {
            "uplink_mbps": 1000,
            "downlink_mbps": 10000,
            "latency_ms": 10,
            "jitter_ms": 2,
            "packet_loss_pct": 0.01,
        }

        # Test with 100% pass probability
        high_prob_samples = [
            generate_vr_gaming_measurements(pass_probability=1.0, seed=i)
            for i in range(100)
        ]

        # Count how many metrics pass on average
        high_prob_pass_rates = []
        for sample in high_prob_samples:
            num_passing = sum([
                sample["uplink_mbps"] >= THRESHOLDS["uplink_mbps"],
                sample["downlink_mbps"] >= THRESHOLDS["downlink_mbps"],
                sample["latency_ms"] <= THRESHOLDS["latency_ms"],
                sample["jitter_ms"] <= THRESHOLDS["jitter_ms"],
                sample["packet_loss_pct"] <= THRESHOLDS["packet_loss_pct"],
            ])
            high_prob_pass_rates.append(num_passing / 5)

        # Test with 0% pass probability
        low_prob_samples = [
            generate_vr_gaming_measurements(pass_probability=0.0, seed=i)
            for i in range(100)
        ]

        low_prob_pass_rates = []
        for sample in low_prob_samples:
            num_passing = sum([
                sample["uplink_mbps"] >= THRESHOLDS["uplink_mbps"],
                sample["downlink_mbps"] >= THRESHOLDS["downlink_mbps"],
                sample["latency_ms"] <= THRESHOLDS["latency_ms"],
                sample["jitter_ms"] <= THRESHOLDS["jitter_ms"],
                sample["packet_loss_pct"] <= THRESHOLDS["packet_loss_pct"],
            ])
            low_prob_pass_rates.append(num_passing / 5)

        # High probability should have higher average pass rate
        avg_high = statistics.mean(high_prob_pass_rates)
        avg_low = statistics.mean(low_prob_pass_rates)
        assert avg_high > avg_low

    def test_pass_probability_70_percent(self):
        """Default 70% pass probability should result in ~70% metrics passing."""
        THRESHOLDS = {
            "uplink_mbps": 1000,
            "downlink_mbps": 10000,
            "latency_ms": 10,
            "jitter_ms": 2,
            "packet_loss_pct": 0.01,
        }

        samples = [
            generate_vr_gaming_measurements(pass_probability=0.7, seed=i)
            for i in range(500)
        ]

        pass_rates = []
        for sample in samples:
            num_passing = sum([
                sample["uplink_mbps"] >= THRESHOLDS["uplink_mbps"],
                sample["downlink_mbps"] >= THRESHOLDS["downlink_mbps"],
                sample["latency_ms"] <= THRESHOLDS["latency_ms"],
                sample["jitter_ms"] <= THRESHOLDS["jitter_ms"],
                sample["packet_loss_pct"] <= THRESHOLDS["packet_loss_pct"],
            ])
            pass_rates.append(num_passing / 5)

        avg_pass_rate = statistics.mean(pass_rates)
        # Should be around 70%, allow ±10% due to Gaussian variance
        assert 0.60 <= avg_pass_rate <= 0.80

    def test_uplink_in_reasonable_range(self):
        """Uplink throughput should be in a reasonable range."""
        samples = [
            generate_vr_gaming_measurements(seed=i)["uplink_mbps"]
            for i in range(100)
        ]
        # All values should be non-negative and < 2000 Mbps (reasonable upper bound)
        assert all(0 <= s < 2000 for s in samples)

    def test_downlink_in_reasonable_range(self):
        """Downlink throughput should be in a reasonable range."""
        samples = [
            generate_vr_gaming_measurements(seed=i)["downlink_mbps"]
            for i in range(100)
        ]
        # All values should be non-negative and < 20000 Mbps (reasonable upper bound)
        assert all(0 <= s < 20000 for s in samples)

    def test_latency_in_reasonable_range(self):
        """Latency should be in a reasonable range."""
        samples = [
            generate_vr_gaming_measurements(seed=i)["latency_ms"]
            for i in range(100)
        ]
        # All values should be >= 0.1ms and < 50ms (reasonable upper bound)
        assert all(0.1 <= s < 50 for s in samples)

    def test_jitter_in_reasonable_range(self):
        """Jitter should be in a reasonable range."""
        samples = [
            generate_vr_gaming_measurements(seed=i)["jitter_ms"]
            for i in range(100)
        ]
        # All values should be >= 0.1ms and < 10ms (reasonable upper bound)
        assert all(0.1 <= s < 10 for s in samples)

    def test_packet_loss_in_reasonable_range(self):
        """Packet loss should be in a reasonable range."""
        samples = [
            generate_vr_gaming_measurements(seed=i)["packet_loss_pct"]
            for i in range(100)
        ]
        # All values should be between 0% and 1% (reasonable for VR gaming)
        assert all(0.0 <= s <= 1.0 for s in samples)

    def test_probabilistic_variation_between_runs(self):
        """Multiple runs without seed should produce different results."""
        results = [generate_vr_gaming_measurements() for _ in range(10)]
        # Not all results should be identical
        unique_uplinks = set(r["uplink_mbps"] for r in results)
        assert len(unique_uplinks) > 1
