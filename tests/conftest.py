import copy
import json
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from herdr_mcp.auth import BearerTokenMiddleware
from herdr_mcp.config import Settings
from herdr_mcp.herdr.client import AgentRecord, Herdr, RunResult
from herdr_mcp.herdr.exceptions import HerdrError
from herdr_mcp.history import ConversationHistory, SqliteConversationHistory
from herdr_mcp.server import build_app

SNAPSHOT_ARGS = ("herdr", "api", "snapshot")
SCREEN_TEXT = (
    "\nTask: rename the config loader  \n\n\n\nRunning tests   \n\n\n\n12 passed\n\n\n\nDone\n"
)
TRIMMED_SCREEN = "Task: rename the config loader\n\nRunning tests\n\n12 passed\n\nDone"
TOKEN = "t" * 32
SETTING_VARIABLES = [
    "HERDR_MCP_TOKEN",
    "HERDR_MCP_PUBLIC_HOST",
    "HERDR_MCP_HOST",
    "HERDR_MCP_PORT",
    "HERDR_BIN",
    "HERDR_MCP_LOG_HEADERS",
    "HERDR_MCP_HISTORY_PATH",
]
INVALID_SETTINGS = [
    ("HERDR_MCP_TOKEN", None),
    ("HERDR_MCP_TOKEN", "t" * 31),
    ("HERDR_MCP_TOKEN", "t" * 16 + " " + "t" * 16),
    ("HERDR_MCP_PUBLIC_HOST", "mcp.example.com:443"),
    ("HERDR_MCP_HOST", "localhost:80"),
    ("HERDR_MCP_PORT", "0"),
    ("HERDR_MCP_PORT", "0" * 5000 + "8000" + "0"),
    ("HERDR_MCP_HISTORY_PATH", "relative/history.sqlite3"),
    ("HERDR_MCP_HISTORY_PATH", "~no-such-user-for-herdr-mcp/history.sqlite3"),
]
UNAUTHORIZED_REQUESTS = {
    "missing header": ("/mcp", {}),
    "wrong token": ("/mcp", {"Authorization": f"Bearer {'x' * 32}"}),
    "token query": (f"/mcp?token={TOKEN}", {}),
}
EXPECTED_RECORDS = [
    AgentRecord("alpha", "w1:p1", "claude", "working", "api", True, 1, 2),
    AgentRecord(None, "w1:p2", "codex", "idle", "api", True, 1, 2),
    AgentRecord("beta", "w2:p1", "claude", "blocked", "web", False, 1, 1),
    AgentRecord("gamma", "w3:p1", "codex", "done", None, None, None, 1),
]
ORCHESTRATOR_SUMMARY = {"target": "alpha", "kind": "claude", "status": "idle", "workspace": "api"}
EARLIER_AND_NEW_ANSWER = (
    "> list the open pull requests\n\nNo pull requests are open.\n\n"
    "> is anything blocked\n\nNothing is blocked.   \n\n\n"
)
TRIMMED_EARLIER_AND_NEW_ANSWER = (
    "> list the open pull requests\n\nNo pull requests are open.\n\n"
    "> is anything blocked\n\nNothing is blocked."
)
UNREADABLE_STDERR = {
    "plain text": "panic",
    "oversized integer": "1" * 5000,
    "deep nesting": "[" * 10000 + "]" * 10000,
}
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
INITIALIZED_NOTIFICATION = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


LIST_AGENTS_CALL = tool_call("list_agents", {})


def screen_read_args(target: str) -> tuple[str, ...]:
    return ("herdr", "agent", "read", target, "--source", "visible")


READ_ALPHA_ARGS = screen_read_args("alpha")


def prompt_args(name: str, text: str, wait: bool = True) -> tuple[str, ...]:
    if not wait:
        return ("herdr", "agent", "prompt", name, text)
    return ("herdr", "agent", "prompt", name, text, "--wait", "--timeout", "30000")


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], RunResult | Exception]) -> None:
        self._results = results
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []

    def __call__(self, args: list[str], timeout: float) -> RunResult:
        self.calls.append(tuple(args))
        self.timeouts.append(timeout)
        result = self._results[tuple(args)]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def snapshot_json() -> dict[str, Any]:
    return {
        "id": "1",
        "result": {
            "type": "session_snapshot",
            "snapshot": {
                "agents": [
                    _agent("w1:p1", "w1", "w1:t1", "claude", "working", name="alpha"),
                    _agent("w1:p2", "w1", "w1:t1", "codex", "idle"),
                    _agent("w2:p1", "w2", "w2:t1", "claude", "blocked", name="beta"),
                    _agent("w3:p1", "w3", "w3:t1", "codex", "done", name="gamma"),
                ],
                "workspaces": [
                    _workspace("w1", "api", is_linked_worktree=False, path="/repo/api"),
                    _workspace("w2", "web", is_linked_worktree=True, path="/repo/web-1"),
                ],
                "tabs": [
                    {"tab_id": "w1:t1", "workspace_id": "w1", "number": 1, "label": "1"},
                    {"tab_id": "w2:t1", "workspace_id": "w2", "number": 1, "label": "1"},
                ],
            },
        },
    }


@pytest.fixture
def fake_runner() -> type[FakeRunner]:
    return FakeRunner


@pytest.fixture
def snapshot_herdr(snapshot_json, fake_runner) -> Herdr:
    return Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))


@pytest.fixture(params=["herdr_error", "unexpected_exception"])
def failing_herdr(request, fake_runner) -> Herdr:
    if request.param == "herdr_error":
        return Herdr("herdr", fake_runner({SNAPSHOT_ARGS: failed_with("server_not_running")}))
    return Herdr("herdr", fake_runner({}))


@pytest.fixture
def auth_client() -> TestClient:
    stub = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"))])
    return TestClient(BearerTokenMiddleware(stub, TOKEN))


def orchestrator_snapshot(
    snapshot_json: dict[str, Any],
    status: str = "idle",
    shared_tab: bool = False,
    tab_number: int = 1,
    name: str | None = "alpha",
    kind: str | None = "claude",
) -> dict[str, Any]:
    payload = copy.deepcopy(snapshot_json)
    snapshot = payload["result"]["snapshot"]
    snapshot["agents"][0]["agent_status"] = status
    if kind is None:
        del snapshot["agents"][0]["agent"]
    else:
        snapshot["agents"][0]["agent"] = kind
    snapshot["tabs"][0]["number"] = tab_number
    if name is None:
        del snapshot["agents"][0]["name"]
    else:
        snapshot["agents"][0]["name"] = name
    if not shared_tab:
        snapshot["agents"][1]["tab_id"] = "w1:t2"
        snapshot["tabs"].append(
            {"tab_id": "w1:t2", "workspace_id": "w1", "number": 3, "label": "3"}
        )
    return payload


def succeeded(payload: Any) -> RunResult:
    return RunResult(exit_code=0, stdout=json.dumps(payload), stderr="")


def settled_as(status: str) -> RunResult:
    agent = {
        "terminal_id": "t1",
        "pane_id": "w1:p1",
        "workspace_id": "w1",
        "tab_id": "w1:t1",
        "agent": "claude",
        "name": "alpha",
        "agent_status": status,
        "focused": False,
        "revision": 7,
    }
    return succeeded({"id": "1", "result": {"type": "agent_prompted", "agent": agent}})


def failed_with(code: str) -> RunResult:
    stderr = json.dumps({"error": {"code": code, "message": "synthetic failure"}})
    return RunResult(exit_code=1, stdout="", stderr=stderr)


EXCHANGE_ID = "0a1b2c3d" * 4
RECAP_SENTENCE = (
    " After your answer or your numbered options, call save_reply_recap from the herdr MCP server "
    "with exchange_id 0a1b2c3d0a1b2c3d0a1b2c3d0a1b2c3d and a one-line recap, then end your turn."
)
RECAP = "The tests passed."
MESSAGE = "run the tests"
FRAMED_MESSAGE = (
    'Voice message from the engineer, relayed by Grok: "run the tests". '
    "Reply in plain text and do not open a question dialog. "
    "If you need me to choose, list numbered options." + RECAP_SENTENCE
)
FRAMED_BUSY_MESSAGE = (
    'Voice message from the engineer, relayed by Grok: "run the tests". '
    "Reply in plain text and do not open a question dialog. "
    "If you need me to choose, list numbered options. "
    "If you are in the middle of a task, finish it first unless this message asks you to stop."
    + RECAP_SENTENCE
)
QUOTED_MESSAGE = 'should we use "A" or {B}?'
FRAMED_QUOTED_MESSAGE = (
    'Voice message from the engineer, relayed by Grok: "should we use "A" or {B}?". '
    "Reply in plain text and do not open a question dialog. "
    "If you need me to choose, list numbered options." + RECAP_SENTENCE
)
LONGEST_MESSAGE = "a" * 2000
FRAMED_LONGEST_MESSAGE = (
    'Voice message from the engineer, relayed by Grok: "' + "a" * 2000 + '". '
    "Reply in plain text and do not open a question dialog. "
    "If you need me to choose, list numbered options." + RECAP_SENTENCE
)
UNSENDABLE_CHARACTER = "The message contains a character I cannot send."
NOT_ORCHESTRATOR = "I can only send messages to an orchestrator agent."
AGENT_BLOCKED = "That agent is waiting on a dialog, so I did not send the message."
MAYBE_SENT = "The message may have been sent. Check the agent's activity before you send it again."
BUSY = "That agent is busy, so I did not send the message."
SEND_MESSAGE_REFUSALS = [
    (
        "w1:p1",
        MESSAGE,
        {},
        [],
        "Name the agent instead of its pane. You can name it with herdr agent rename.",
    ),
    ("Alpha!", MESSAGE, {}, [], "That is not a valid agent name."),
    ("alpha", "run\0 the tests", {}, [], UNSENDABLE_CHARACTER),
    ("alpha", "run the tests\nnow", {}, [], UNSENDABLE_CHARACTER),
    ("alpha", "run\x1b[201~ the tests", {}, [], UNSENDABLE_CHARACTER),
    ("delta", MESSAGE, {}, [SNAPSHOT_ARGS], "No agent named delta is running."),
    (
        "alpha",
        MESSAGE,
        {"shared_tab": True},
        [SNAPSHOT_ARGS],
        "That tab has more than one agent, so I did not send the message.",
    ),
    ("alpha", MESSAGE, {"tab_number": 2}, [SNAPSHOT_ARGS], NOT_ORCHESTRATOR),
    ("beta", MESSAGE, {}, [SNAPSHOT_ARGS], NOT_ORCHESTRATOR),
    ("gamma", MESSAGE, {}, [SNAPSHOT_ARGS], NOT_ORCHESTRATOR),
    ("rev-main", MESSAGE, {"name": "rev-main"}, [SNAPSHOT_ARGS], NOT_ORCHESTRATOR),
    ("hm-rev-main", MESSAGE, {"name": "hm-rev-main"}, [SNAPSHOT_ARGS], NOT_ORCHESTRATOR),
    ("alpha", MESSAGE, {"status": "working", "kind": "codex"}, [SNAPSHOT_ARGS], BUSY),
    ("alpha", MESSAGE, {"status": "working", "kind": None}, [SNAPSHOT_ARGS], BUSY),
    ("alpha", MESSAGE, {"status": "blocked"}, [SNAPSHOT_ARGS], AGENT_BLOCKED),
    (
        "alpha",
        MESSAGE,
        {"status": "unknown"},
        [SNAPSHOT_ARGS],
        "I cannot tell whether that agent is ready, so I did not send the message.",
    ),
]
UNSETTLED_PROMPT_RESULTS = [
    (RunResult(0, "{}", ""), "result"),
    (settled_as("working"), "result.agent.agent_status"),
]
PROMPT_FAILURE_SENTENCES = [
    (failed_with("agent_blocked"), AGENT_BLOCKED),
    (
        failed_with("agent_not_ready"),
        "That agent is not ready for a message, so I did not send it.",
    ),
    (failed_with("agent_not_found"), "No agent named alpha is running."),
    (failed_with("agent_prompt_failed"), MAYBE_SENT),
    (failed_with("timeout"), MAYBE_SENT),
    (failed_with("agent_prompt_stalled"), MAYBE_SENT),
    (failed_with("agent_not_running"), MAYBE_SENT),
    (failed_with("server_unavailable"), MAYBE_SENT),
    (HerdrError("timeout", "agent prompt", None), MAYBE_SENT),
    (settled_as("working"), MAYBE_SENT),
]


FIXED_NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)


class SettableClock:
    def __init__(self) -> None:
        self.now = FIXED_NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> SettableClock:
    return SettableClock()


@pytest.fixture
def history_path(tmp_path) -> Path:
    return tmp_path / "state" / "history.sqlite3"


@pytest.fixture
def history(history_path, clock) -> SqliteConversationHistory:
    return SqliteConversationHistory(history_path, clock)


FIRST_EXCHANGE_ID = "a" * 32
SECOND_EXCHANGE_ID = "b" * 32


def numbered_exchange_id(number: int) -> str:
    return f"{number:032x}"


def count_history_table_rows(path, table: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture(autouse=True)
def fixed_exchange_id(monkeypatch) -> str:
    monkeypatch.setattr("herdr_mcp.server.secrets.token_hex", lambda nbytes: EXCHANGE_ID)
    return EXCHANGE_ID


@contextmanager
def mcp_session(
    herdr: Herdr, history: ConversationHistory | None = None
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with tempfile.TemporaryDirectory() as directory:
        if history is None:
            history = SqliteConversationHistory(
                Path(directory) / "history.sqlite3", SettableClock()
            )
        with _initialized_client(herdr, history) as session:
            yield session


@contextmanager
def _initialized_client(
    herdr: Herdr, history: ConversationHistory
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    settings = Settings(
        token=TOKEN,
        public_host=None,
        host="127.0.0.1",
        port=8000,
        herdr_binary="herdr",
        log_headers=False,
        history_path=Path("/unused/history.sqlite3"),
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(
        build_app(settings, herdr, history), base_url="http://127.0.0.1:8000"
    ) as client:
        response = client.post("/mcp", headers=headers, json=INITIALIZE_REQUEST)
        headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        client.post("/mcp", headers=headers, json=INITIALIZED_NOTIFICATION)
        yield client, headers


def _agent(
    pane_id: str, workspace_id: str, tab_id: str, kind: str, status: str, name: str | None = None
) -> dict[str, Any]:
    agent = {
        "pane_id": pane_id,
        "workspace_id": workspace_id,
        "tab_id": tab_id,
        "agent": kind,
        "agent_status": status,
        "cwd": "/repo",
    }
    if name is not None:
        agent["name"] = name
    return agent


def _workspace(
    workspace_id: str, label: str, is_linked_worktree: bool, path: str
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "label": label,
        "worktree": {"checkout_path": path, "is_linked_worktree": is_linked_worktree},
    }
