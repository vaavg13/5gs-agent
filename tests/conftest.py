"""Shared fixtures for inspect_5gs_sandbox tests."""

import gc
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def cleanup_between_tests():
    """Clean up resources between tests to prevent OOM."""
    yield
    gc.collect()


@pytest.fixture
def mock_subprocess_run(mocker):
    """Mock subprocess.run for Docker Compose operations."""
    return mocker.patch("inspect_5gs_sandbox._compose_ops.subprocess.run")


@pytest.fixture
def successful_compose_result():
    """Successful docker compose up result."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


@pytest.fixture
def port_conflict_result():
    """Docker compose result simulating port conflict."""
    result = MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = "Bind for 0.0.0.0:9092 failed: port is already allocated"
    return result


@pytest.fixture
def compose_ps_json():
    """Mock docker compose ps --format json output."""
    return '''{"Service":"nrf","ID":"abc123"}
{"Service":"amf","ID":"def456"}
{"Service":"smf","ID":"ghi789"}
{"Service":"upf","ID":"jkl012"}
{"Service":"gnb","ID":"mno345"}'''


@pytest.fixture
def ps_result(compose_ps_json):
    """Successful docker compose ps result."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = compose_ps_json
    result.stderr = ""
    return result
