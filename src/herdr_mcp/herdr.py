"""The herdr CLI client. It is the only module that starts a subprocess or reads herdr's JSON."""

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

TIMEOUT_SECONDS = 10.0
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
    """A herdr call failed. `code` is herdr's error code or one this module assigns."""

    def __init__(
        self, code: str, command: str, exit_code: int | None, field: str | None = None
    ) -> None:
        super().__init__(f"herdr {command} failed with {code} (exit code {exit_code})")
        self.code = code
        self.command = command
        self.exit_code = exit_code
        self.field = field


def subprocess_runner(args: list[str], timeout: float) -> RunResult:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HerdrError("timeout", " ".join(args[1:]), None) from None
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class AgentRecord:
    name: str | None
    pane_id: str
    kind: str
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
        payload = self._query(SNAPSHOT_ARGS)
        try:
            return _parse_snapshot(payload)
        except _MalformedOutput as error:
            raise HerdrError("unexpected_output", " ".join(SNAPSHOT_ARGS), 0, str(error)) from None

    def _query(self, args: list[str]) -> Any:
        command = " ".join(args)
        result = self._run([self._binary, *args], timeout=TIMEOUT_SECONDS)
        if result.exit_code == INVALID_SYNTAX_EXIT_CODE:
            raise HerdrError("invalid_syntax", command, result.exit_code)
        if result.exit_code != 0:
            raise HerdrError(_stderr_error_code(result.stderr), command, result.exit_code)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise HerdrError("unexpected_output", command, 0) from None


class _MalformedOutput(Exception):
    """herdr's JSON lacks a field or has one of the wrong type. The message is the field name."""


def _parse_snapshot(payload: Any) -> list[AgentRecord]:
    snapshot = _as_object(_as_object(_as_object(payload).get("result")).get("snapshot"))
    agents = [_as_object(item) for item in _list_field(snapshot, "agents")]
    workspaces = {
        _required_str(entry, "workspace_id"): entry
        for entry in map(_as_object, _list_field(snapshot, "workspaces"))
    }
    tabs = {
        _required_str(entry, "tab_id"): entry
        for entry in map(_as_object, _list_field(snapshot, "tabs"))
    }
    tab_ids = [_optional_str(agent, "tab_id") for agent in agents]
    agents_per_tab = Counter(tab_id for tab_id in tab_ids if tab_id is not None)
    return [
        _record(agent, workspaces, tabs, agents_per_tab[tab_id] if tab_id is not None else 1)
        for agent, tab_id in zip(agents, tab_ids, strict=True)
    ]


def _record(
    agent: dict[str, Any],
    workspaces: dict[str, dict[str, Any]],
    tabs: dict[str, dict[str, Any]],
    agents_in_tab: int,
) -> AgentRecord:
    workspace = workspaces.get(_optional_str(agent, "workspace_id") or "")
    tab = tabs.get(_optional_str(agent, "tab_id") or "")
    return AgentRecord(
        name=_optional_str(agent, "name"),
        pane_id=_required_str(agent, "pane_id"),
        kind=_required_str(agent, "agent"),
        status=_required_str(agent, "agent_status"),
        workspace_label=_optional_str(workspace, "label") if workspace is not None else None,
        is_main_checkout=_is_main_checkout(workspace),
        tab_number=_optional_int(tab, "number") if tab is not None else None,
        agents_in_tab=agents_in_tab,
    )


def _is_main_checkout(workspace: dict[str, Any] | None) -> bool | None:
    if workspace is None or "worktree" not in workspace:
        return None
    is_linked = _as_object(workspace["worktree"]).get("is_linked_worktree")
    if not isinstance(is_linked, bool):
        raise _MalformedOutput("is_linked_worktree")
    return not is_linked


def _stderr_error_code(stderr: str) -> str:
    try:
        code = json.loads(stderr)["error"]["code"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "unreadable_error"
    return code if isinstance(code, str) else "unreadable_error"


def _list_field(container: dict[str, Any], key: str) -> list[Any]:
    value = container.get(key)
    if not isinstance(value, list):
        raise _MalformedOutput(key)
    return value


def _as_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _MalformedOutput("object")
    return value


def _required_str(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        raise _MalformedOutput(key)
    return value


def _optional_str(entry: dict[str, Any], key: str) -> str | None:
    return _required_str(entry, key) if key in entry else None


def _optional_int(entry: dict[str, Any], key: str) -> int | None:
    if key not in entry:
        return None
    value = entry[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise _MalformedOutput(key)
    return value
