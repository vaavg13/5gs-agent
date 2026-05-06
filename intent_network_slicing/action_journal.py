"""Action journaling for intent-oriented remediation tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from inspect_ai.util import StoreModel, store_as


class ActionRecord(BaseModel):
    """One state-changing action attempted during a sample run."""

    timestamp: str
    tool_name: str
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    old_value: Any = None
    new_value: Any = None
    success: bool
    restart_required: bool = False
    risk_class: str = "medium"
    details: str = ""


class ActionJournal(StoreModel):
    """Per-sample action history used by tools and later scorers."""

    actions: list[ActionRecord] = Field(default_factory=list)


def record_action(
    *,
    tool_name: str,
    target: str,
    parameters: dict[str, Any] | None = None,
    old_value: Any = None,
    new_value: Any = None,
    success: bool,
    restart_required: bool = False,
    risk_class: str = "medium",
    details: str = "",
) -> ActionRecord:
    """Append a structured action record to the sample store."""
    journal = store_as(ActionJournal)
    action = ActionRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool_name=tool_name,
        target=target,
        parameters=parameters or {},
        old_value=old_value,
        new_value=new_value,
        success=success,
        restart_required=restart_required,
        risk_class=risk_class,
        details=details,
    )
    journal.actions = [*journal.actions, action]
    return action
