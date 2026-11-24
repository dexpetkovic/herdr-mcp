"""The herdr CLI client and the agent records it builds from herdr's snapshot."""

import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from herdr_mcp.herdr.exceptions import HerdrError
from herdr_mcp.herdr.pydantic import PromptResponse, Snapshot, SnapshotResponse
from herdr_mcp.herdr.validator import error_code_from_stderr, validate_response_json

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
        response = validate_response_json(SnapshotResponse, stdout, _operation_name(SNAPSHOT_ARGS))
        return _agent_records_from_snapshot(response.result.snapshot)

    def read_screen(self, target: str) -> str:
        return self._query(["agent", "read", target, "--source", "visible"])

    def prompt(self, name: str, text: str, wait_ms: int) -> str:
        """Waits up to `wait_ms` for herdr to report a settled agent status and returns it."""
        args = ["agent", "prompt", name, text, "--wait", "--timeout", str(wait_ms)]
        stdout = self._query(args, timeout=wait_ms / 1000 + PROMPT_TIMEOUT_MARGIN_SECONDS)
        response = validate_response_json(PromptResponse, stdout, _operation_name(args))
        return response.result.agent.agent_status

    def _query(self, args: list[str], timeout: float = TIMEOUT_SECONDS) -> str:
        command = _operation_name(args)
        result = self._run([self._binary, *args], timeout=timeout)
        if result.exit_code == INVALID_SYNTAX_EXIT_CODE:
            raise HerdrError("invalid_syntax", command, result.exit_code)
        if result.exit_code != 0:
            raise HerdrError(error_code_from_stderr(result.stderr), command, result.exit_code)
        return result.stdout


def _agent_records_from_snapshot(snapshot: Snapshot) -> list[AgentRecord]:
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
