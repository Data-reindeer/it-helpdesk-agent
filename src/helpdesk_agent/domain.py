"""Strict contracts shared by orchestration, provider and API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Query(StrictModel):
    tool: Literal[
        "search_kb",
        "get_service_status",
        "get_recent_changes",
        "get_current_user_context",
        "search_resolution_history",
        "evaluate_action_policy",
        "get_action_result",
    ]
    query: str = Field(max_length=300)
    service: str = Field(max_length=40)


class Decision(StrictModel):
    kind: Literal["query", "clarify", "guide", "action", "incident", "escalate"]
    # No free-form operational instructions: approved runbook steps are rendered by server.
    question: str = Field(max_length=500)
    diagnosis: str = Field(max_length=800)
    evidence_ids: list[str] = Field(max_length=10)
    queries: list[Query] = Field(max_length=4)
    runbook_id: str = Field(max_length=40)
    action: Literal["none", "password_reset", "access_request"]
    resource: str = Field(max_length=80)
    justification: str = Field(max_length=600)
    # Every selected runbook condition must map to evidence; server verifies IDs, human eval semantics.
    condition_evidence: list[str] = Field(max_length=8)


class NewSession(StrictModel):
    employee_id: str = Field(pattern=r"^EMP-\d{3}$")


class Message(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class Confirm(StrictModel):
    action_id: str
    approve: bool


class Feedback(StrictModel):
    resolved: bool


class NewIssue(StrictModel):
    title: str = Field(min_length=1, max_length=150)
