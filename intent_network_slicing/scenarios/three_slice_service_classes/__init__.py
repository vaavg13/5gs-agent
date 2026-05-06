"""Open5GS 5G SA (Standalone) environment.

Directory Structure:
    compose.yaml        - Full 5G SA stack (all 10 NFs + UERANSIM)
    compose-lite.yaml   - Minimal stack (NRF, AMF, SMF, UPF + UERANSIM)
    .env               - Environment variables
    config/            - Network function configurations
    scripts/           - Deployment scripts
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
CONFIG_DIR = PACKAGE_DIR / "config"
SCRIPTS_DIR = PACKAGE_DIR / "scripts"
COMPOSE_FILE = PACKAGE_DIR / "compose.yaml"
COMPOSE_LITE_FILE = PACKAGE_DIR / "compose-lite.yaml"

__all__ = ["PACKAGE_DIR", "CONFIG_DIR", "SCRIPTS_DIR", "COMPOSE_FILE", "COMPOSE_LITE_FILE"]
