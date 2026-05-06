"""Shared validation utilities for network slicing tools.

Provides canonical constants and validation helpers used across retrieval and action modules.
"""

from __future__ import annotations

# Canonical set of valid service names for network operations
VALID_SERVICES: set[str] = {
    "amf",
    "smf",
    "upf",
    "nrf",
    "gnb",
    "mongo",
    "ue_premium",
    "ue_background",
    "ue_control",
}


def validate_service(service: str, valid_set: set[str] | None = None) -> str | None:
    """Validate a service name.

    Args:
        service: Service name to validate.
        valid_set: Optional custom set of valid services. If None, uses VALID_SERVICES.

    Returns:
        None if valid, error message string if invalid.
    """
    if not isinstance(service, str):
        return f"Invalid service type: expected string, got {type(service).__name__}"

    normalized = service.lower().strip()
    allowed = valid_set if valid_set is not None else VALID_SERVICES

    if normalized not in allowed:
        return f"Invalid service: '{service}'. Valid services: {', '.join(sorted(allowed))}"

    return None
