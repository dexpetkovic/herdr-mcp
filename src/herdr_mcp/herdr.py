"""The herdr CLI client. It is the only module that starts a subprocess or reads herdr's JSON."""

import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, NonNegativeInt, ValidationError

TIMEOUT_SECONDS = 10.0
PROMPT_TIMEOUT_MARGIN_SECONDS = 5.0
INVALID_SYNTAX_EXIT_CODE = 2
SNAPSHOT_ARGS = ["api", "snapshot"]


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def __call__(self, args: list[str], timeout: float) -> RunResult: ...


class HerdrError(Exception):
    """A herdr call failed. `field` is the dotted path of malformed response data, when known."""

    def __init__(
        self, code: str, command: str, exit_code: int | None, field: str | None = None
    ) -> None:
        super().__init__(f"herdr {command} failed with {code} (exit code {exit_code})")
        self.code = code
        self.command = command
        self.exit_code = exit_code
        self.field = field


def _operation_name(args: list[str]) -> str:
    """Names the herdr operation without its targets or prompt text, which must stay out of logs."""
    return " ".join(args[:2])


def subprocess_runner(args: list[str], timeout: float) -> RunResult:
    command = _operation_name(args[1:])
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise HerdrError("timeout", command, None) from None
    except OSError as error:
        raise HerdrError("launch_failed", command, None) from error
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class AgentRecord:
    name: str | None
    pane_id: str
    kind: str | None
    status: str
    workspace_label: str | None
    is_main_checkout: bool | None
    tab_number: int | None
    agents_in_tab: int


class Herdr:
    def __init__(self, binary: str, run: Runner) -> None:
        self._binary = binary
        self._run = run

    def snapshot(self) -> list[AgentRecord]:
        stdout = self._query(SNAPSHOT_ARGS)
        response = _validate_response_json(_SnapshotResponse, stdout, SNAPSHOT_ARGS)
        return _agent_records(response.result.snapshot)

    def read_screen(self, target: str) -> str:
        return self._query(["agent", "read", target, "--source", "visible"])

    def prompt(self, name: str, text: str, wait_ms: int) -> str:
        """Waits up to `wait_ms` for herdr to report a settled agent status and returns it."""
        args = ["agent", "prompt", name, text, "--wait", "--timeout", str(wait_ms)]
        stdout = self._query(args, timeout=wait_ms / 1000 + PROMPT_TIMEOUT_MARGIN_SECONDS)
        return _validate_response_json(_PromptResponse, stdout, args).result.agent.agent_status

    def _query(self, args: list[str], timeout: float = TIMEOUT_SECONDS) -> str:
        command = _operation_name(args)
        result = self._run([self._binary, *args], timeout=timeout)
        if result.exit_code == INVALID_SYNTAX_EXIT_CODE:
            raise HerdrError("invalid_syntax", command, result.exit_code)
        if result.exit_code != 0:
            raise HerdrError(_stderr_error_code(result.stderr), command, result.exit_code)
        return result.stdout


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


class _Snapshot(_WireModel):
    agents: list[_AgentRow]
    workspaces: list[_WorkspaceRow]
    tabs: list[_TabRow]


class _SnapshotResult(_WireModel):
    snapshot: _Snapshot


class _SnapshotResponse(_WireModel):
    result: _SnapshotResult


class _PromptedAgent(_WireModel):
    agent_status: Literal["idle", "done", "blocked"]


class _PromptResult(_WireModel):
    agent: _PromptedAgent


class _PromptResponse(_WireModel):
    result: _PromptResult


WireModel = TypeVar("WireModel", bound=_WireModel)


def _validate_response_json(model: type[WireModel], stdout: str, args: list[str]) -> WireModel:
    try:
        return model.model_validate_json(stdout)
    except ValidationError as error:
        location = error.errors()[0]["loc"]
        field = ".".join(str(part) for part in location) or None
        raise HerdrError("unexpected_output", _operation_name(args), 0, field) from None


def _agent_records(snapshot: _Snapshot) -> list[AgentRecord]:
    workspaces = {workspace.workspace_id: workspace for workspace in snapshot.workspaces}
    tab_numbers = {tab.tab_id: tab.number for tab in snapshot.tabs}
    agents_per_tab = Counter(agent.tab_id for agent in snapshot.agents)
    records = []
    for agent in snapshot.agents:
        workspace = workspaces.get(agent.workspace_id)
        worktree = workspace.worktree if workspace is not None else None
        records.append(
            AgentRecord(
                name=agent.name,
                pane_id=agent.pane_id,
                kind=agent.agent,
                status=agent.agent_status,
                workspace_label=workspace.label if workspace is not None else None,
                is_main_checkout=not worktree.is_linked_worktree if worktree is not None else None,
                tab_number=tab_numbers.get(agent.tab_id),
                agents_in_tab=agents_per_tab[agent.tab_id],
            )
        )
    return records


class _ErrorDetail(_WireModel):
    code: str


class _ErrorResponse(_WireModel):
    error: _ErrorDetail


def _stderr_error_code(stderr: str) -> str:
    try:
        return _ErrorResponse.model_validate_json(stderr).error.code
    except ValidationError:
        return "unreadable_error"
