"""
Tests for Prometheus port allocation in inspect_5gs_sandbox.

These tests verify that parallel samples get unique Prometheus ports
to avoid "port is already allocated" errors.

BUG LOCATION: open5gs.py:253 passes None for env_vars, so no unique
PROMETHEUS_PORT is ever assigned to parallel samples.
"""

import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# Fixtures for capturing deploy_stack calls
# ============================================================================


@pytest.fixture
def deploy_stack_capture():
    """Capture env_vars passed to deploy_stack via run_in_process."""
    captured = {"env_vars_list": []}

    async def capture_run_in_process(func, *args, **kwargs):
        if func.__name__ == "deploy_stack":
            env_vars = args[2] if len(args) > 2 else None
            captured["env_vars_list"].append(env_vars)
            return {"amf": f"container-{len(captured['env_vars_list'])}"}
        return None

    captured["mock"] = capture_run_in_process
    return captured


@pytest.fixture
def mock_sample_init_deps(deploy_stack_capture, tmp_path):
    """Mock all dependencies for sample_init."""
    sample_index = [0]

    # Create temp directory structure with compose.yaml and config dir
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services:\n  amf:\n    image: test\n")

    def mock_sample_active():
        mock = MagicMock()
        mock.sample.id = f"sample-{sample_index[0]:03d}"
        mock.epoch = 0
        sample_index[0] += 1
        return mock

    mocks = {
        "run_in_process": AsyncMock(side_effect=deploy_stack_capture["mock"]),
        "find_compose_file": MagicMock(return_value=compose_file),
        "parse_compose_services": MagicMock(return_value=["amf"]),
        "sample_active": mock_sample_active,
        "_get_impairment_config_path": MagicMock(return_value=None),
    }
    yield mocks
    # Cleanup
    for mock in mocks.values():
        if hasattr(mock, 'reset_mock'):
            mock.reset_mock()


# ============================================================================
# Category A: Port Allocation Bug Tests - MUST FAIL until bug is fixed
# ============================================================================


class TestPortAllocationBug:
    """
    Tests that expose the port allocation bug.

    BUG: open5gs.py:253 passes None for env_vars to deploy_stack,
    so parallel samples all try to bind to the same Prometheus port.
    """

    @pytest.mark.asyncio
    async def test_env_vars_passed_to_deploy_stack_is_not_none(
        self, deploy_stack_capture, mock_sample_init_deps
    ):
        """
        BUG TEST: env_vars must not be None.

        FAILS because open5gs.py:253 passes None.
        """
        with patch.multiple(
            "inspect_5gs_sandbox.open5gs", **mock_sample_init_deps
        ):
            with patch(
                "inspect_5gs_sandbox._health_checks.wait_for_5g_ready",
                new_callable=AsyncMock,
            ):
                from inspect_5gs_sandbox.open5gs import Open5GSSandboxEnvironment

                await Open5GSSandboxEnvironment.sample_init(
                    task_name="test-task", config="/fake/path", metadata={}
                )

        assert deploy_stack_capture["env_vars_list"][0] is not None, (
            "BUG: env_vars is None. See open5gs.py:253"
        )

    @pytest.mark.asyncio
    async def test_prometheus_port_in_env_vars(
        self, deploy_stack_capture, mock_sample_init_deps
    ):
        """
        BUG TEST: PROMETHEUS_PORT must be in env_vars.

        FAILS because env_vars is None (no port assigned).
        """
        with patch.multiple(
            "inspect_5gs_sandbox.open5gs", **mock_sample_init_deps
        ):
            with patch(
                "inspect_5gs_sandbox._health_checks.wait_for_5g_ready",
                new_callable=AsyncMock,
            ):
                from inspect_5gs_sandbox.open5gs import Open5GSSandboxEnvironment

                await Open5GSSandboxEnvironment.sample_init(
                    task_name="test-task", config="/fake/path", metadata={}
                )

        env_vars = deploy_stack_capture["env_vars_list"][0]
        has_port = env_vars is not None and "PROMETHEUS_PORT" in env_vars

        assert has_port, (
            "BUG: PROMETHEUS_PORT not in env_vars. "
            "Parallel samples will conflict on port 9092. "
            "See open5gs.py:253"
        )

    @pytest.mark.asyncio
    async def test_parallel_samples_get_different_ports(
        self, deploy_stack_capture, mock_sample_init_deps
    ):
        """
        BUG TEST: Parallel samples must get different PROMETHEUS_PORTs.

        Actual failure scenario:
        - Sample 001 starts with port 9092
        - Sample 002 starts with port 9092 (CONFLICT!)
        - "Bind for 0.0.0.0:9092 failed: port is already allocated"
        """
        with patch.multiple(
            "inspect_5gs_sandbox.open5gs", **mock_sample_init_deps
        ):
            with patch(
                "inspect_5gs_sandbox._health_checks.wait_for_5g_ready",
                new_callable=AsyncMock,
            ):
                from inspect_5gs_sandbox.open5gs import Open5GSSandboxEnvironment

                await Open5GSSandboxEnvironment.sample_init(
                    task_name="test-task", config="/fake/path", metadata={}
                )
                await Open5GSSandboxEnvironment.sample_init(
                    task_name="test-task", config="/fake/path", metadata={}
                )

        env_list = deploy_stack_capture["env_vars_list"]
        port1 = env_list[0].get("PROMETHEUS_PORT") if env_list[0] else None
        port2 = env_list[1].get("PROMETHEUS_PORT") if env_list[1] else None

        assert port1 != port2, (
            f"BUG: Both samples got port={port1}. "
            "This causes 'port is already allocated'. "
            "See open5gs.py:253"
        )


# ============================================================================
# Category B: deploy_stack capability tests (plumbing verification)
# ============================================================================


class TestDeployStackCapability:
    """Verify deploy_stack CAN handle env_vars when passed correctly."""

    def test_env_vars_passed_to_subprocess(
        self, mock_subprocess_run, successful_compose_result, ps_result
    ):
        """deploy_stack passes env_vars to subprocess.run."""
        from inspect_5gs_sandbox._compose_ops import deploy_stack

        mock_subprocess_run.side_effect = [successful_compose_result, ps_result]

        deploy_stack("test", "/fake/compose.yaml", env_vars={"PROMETHEUS_PORT": "9093"})

        passed_env = mock_subprocess_run.call_args_list[0].kwargs.get("env", {})
        assert passed_env.get("PROMETHEUS_PORT") == "9093"

    def test_port_conflict_error_contains_details(
        self, mock_subprocess_run, port_conflict_result
    ):
        """Port conflict error message contains helpful details."""
        from inspect_5gs_sandbox._compose_ops import deploy_stack

        mock_subprocess_run.return_value = port_conflict_result

        with pytest.raises(RuntimeError) as exc_info:
            deploy_stack("test", "/fake/compose.yaml")

        assert "port is already allocated" in str(exc_info.value)

    @pytest.mark.parametrize(
        "exit_code",
        [1, 2, 124, 137],
        ids=["general_error", "misuse", "timeout", "sigkill"],
    )
    def test_nonzero_exit_raises_runtime_error(self, mock_subprocess_run, exit_code):
        """Non-zero exit codes raise RuntimeError."""
        from inspect_5gs_sandbox._compose_ops import deploy_stack

        result = MagicMock()
        result.returncode = exit_code
        result.stderr = "Command failed"
        mock_subprocess_run.return_value = result

        with pytest.raises(RuntimeError):
            deploy_stack("test", "/fake/compose.yaml")


# ============================================================================
# Category C: Health check ordering tests
# ============================================================================


class TestHealthCheckOrdering:
    """Verify health checks follow correct dependency order."""

    @pytest.mark.asyncio
    async def test_checks_follow_nrf_amf_smf_upf_gnb_order(self):
        """Health checks follow NRF->AMF->SMF->UPF->gNB order."""
        call_order = []

        with patch.multiple(
            "inspect_5gs_sandbox._health_checks",
            check_nrf_sbi=AsyncMock(
                side_effect=lambda p, s: call_order.append("nrf") or True
            ),
            check_amf_ngap=AsyncMock(
                side_effect=lambda p, s: call_order.append("amf") or True
            ),
            check_smf_ready=AsyncMock(
                side_effect=lambda p, s: call_order.append("smf") or True
            ),
            check_upf_ready=AsyncMock(
                side_effect=lambda p, s: call_order.append("upf") or True
            ),
            check_gnb_registered=AsyncMock(
                side_effect=lambda p, s: call_order.append("gnb") or True
            ),
        ):
            from inspect_5gs_sandbox._health_checks import wait_for_5g_ready

            await wait_for_5g_ready("test-project", timeout=5)

        assert call_order == ["nrf", "amf", "smf", "upf", "gnb"]

    @pytest.mark.asyncio
    async def test_failed_nrf_blocks_amf_check(self):
        """NRF failure prevents AMF from being checked."""
        amf_was_checked = False

        def mark_amf(p, s):
            nonlocal amf_was_checked
            amf_was_checked = True
            return True

        with patch.multiple(
            "inspect_5gs_sandbox._health_checks",
            check_nrf_sbi=AsyncMock(return_value=False),
            check_amf_ngap=AsyncMock(side_effect=mark_amf),
            check_smf_ready=AsyncMock(return_value=True),
            check_upf_ready=AsyncMock(return_value=True),
            check_gnb_registered=AsyncMock(return_value=True),
        ):
            from inspect_5gs_sandbox._health_checks import wait_for_5g_ready

            with pytest.raises(TimeoutError):
                await wait_for_5g_ready("test-project", timeout=1)

        assert not amf_was_checked


# ============================================================================
# Category D: Timeout error message tests
# ============================================================================


class TestTimeoutErrorMessages:
    """Verify timeout errors contain helpful diagnostic info."""

    @pytest.mark.parametrize(
        "failing_service,check_fn",
        [
            ("nrf", "check_nrf_sbi"),
            ("amf", "check_amf_ngap"),
            ("smf", "check_smf_ready"),
            ("upf", "check_upf_ready"),
            ("gnb", "check_gnb_registered"),
        ],
    )
    @pytest.mark.asyncio
    async def test_timeout_error_identifies_service(self, failing_service, check_fn):
        """TimeoutError message identifies the failing service."""
        mocks = {
            "check_nrf_sbi": AsyncMock(return_value=True),
            "check_amf_ngap": AsyncMock(return_value=True),
            "check_smf_ready": AsyncMock(return_value=True),
            "check_upf_ready": AsyncMock(return_value=True),
            "check_gnb_registered": AsyncMock(return_value=True),
        }
        mocks[check_fn] = AsyncMock(return_value=False)

        with patch.multiple("inspect_5gs_sandbox._health_checks", **mocks):
            from inspect_5gs_sandbox._health_checks import wait_for_5g_ready

            with pytest.raises(TimeoutError) as exc_info:
                await wait_for_5g_ready("test-project", timeout=1)

        assert failing_service in str(exc_info.value).lower()

    @pytest.mark.parametrize("timeout_seconds", [1, 5, 42, 120])
    @pytest.mark.asyncio
    async def test_timeout_error_includes_timeout_value(self, timeout_seconds):
        """TimeoutError message includes the timeout duration."""
        with patch(
            "inspect_5gs_sandbox._health_checks.check_nrf_sbi",
            AsyncMock(return_value=False),
        ):
            from inspect_5gs_sandbox._health_checks import wait_for_5g_ready

            with pytest.raises(TimeoutError) as exc_info:
                await wait_for_5g_ready("test-project", timeout=timeout_seconds)

        assert str(timeout_seconds) in str(exc_info.value)


# ============================================================================
# Category E: Deploy timeout handling
# ============================================================================


class TestDeployTimeoutHandling:
    """Verify deploy_stack handles subprocess timeouts correctly."""

    def test_subprocess_timeout_raises_runtime_error(self, mock_subprocess_run):
        """Subprocess timeout raises RuntimeError with 'timed out' message."""
        from inspect_5gs_sandbox._compose_ops import deploy_stack

        mock_subprocess_run.side_effect = subprocess.TimeoutExpired(
            cmd=["docker", "compose", "up"], timeout=240
        )

        with pytest.raises(RuntimeError) as exc_info:
            deploy_stack("test", "/fake/compose.yaml")

        assert "timed out" in str(exc_info.value).lower()

    def test_subprocess_timeout_attempts_cleanup(self, mock_subprocess_run):
        """On timeout, teardown is attempted (call_count >= 2)."""
        from inspect_5gs_sandbox._compose_ops import deploy_stack

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=240)
            return MagicMock(returncode=0)

        mock_subprocess_run.side_effect = side_effect

        with pytest.raises(RuntimeError):
            deploy_stack("test", "/fake/compose.yaml")

        assert mock_subprocess_run.call_count >= 2
