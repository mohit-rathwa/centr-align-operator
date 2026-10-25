from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=8, max_length=1200)
    simulate_transient_failure: bool = False

    @field_validator("goal")
    @classmethod
    def trim_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please enter a task.")
        return value


class ApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=500)


class ClarificationRequest(BaseModel):
    message: str = Field(min_length=2, max_length=400)

    @field_validator("message")
    @classmethod
    def trim_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a short clarification.")
        return value


class EventOut(BaseModel):
    id: int
    created_at: str
    kind: str
    title: str
    detail: str
    attempt: int | None = None


class RunOut(BaseModel):
    id: str
    goal: str
    status: str
    created_at: str
    updated_at: str
    plan: dict[str, Any] | None = None
    state: dict[str, Any] = {}
    summary: str | None = None
    error: str | None = None
    pending_approval: dict[str, Any] | None = None
    events: list[EventOut] = []
