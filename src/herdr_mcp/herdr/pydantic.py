"""Strict Pydantic models of the herdr 0.9.5 JSON that the client reads."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt


class _WireModel(BaseModel):
    """Validates the fields read from herdr 0.9.5's bundled schema, `herdr api schema --json`."""

    model_config = ConfigDict(strict=True, frozen=True)


class _WorktreeRow(_WireModel):
    is_linked_worktree: bool


class _WorkspaceRow(_WireModel):
    workspace_id: str
    label: str
    worktree: _WorktreeRow | None = None


class _TabRow(_WireModel):
    tab_id: str
    workspace_id: str
    number: NonNegativeInt


class _AgentRow(_WireModel):
    pane_id: str
    workspace_id: str
    tab_id: str
    agent_status: Literal["idle", "working", "blocked", "done", "unknown"]
    agent: str | None = None
    name: str | None = None


class Snapshot(_WireModel):
    agents: list[_AgentRow]
    workspaces: list[_WorkspaceRow]
    tabs: list[_TabRow]


class _SnapshotResult(_WireModel):
    snapshot: Snapshot


class SnapshotResponse(_WireModel):
    result: _SnapshotResult


class _PromptedAgent(_WireModel):
    agent_status: Literal["idle", "done", "blocked"]


class _PromptResult(_WireModel):
    agent: _PromptedAgent


class PromptResponse(_WireModel):
    result: _PromptResult


class _ErrorDetail(_WireModel):
    code: str


class ErrorResponse(_WireModel):
    error: _ErrorDetail
