import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from herdr_mcp.auth import BearerTokenMiddleware
from herdr_mcp.config import Settings
from herdr_mcp.herdr import AgentRecord, Herdr, Runner, RunResult
from herdr_mcp.server import build_app

SNAPSHOT_ARGS = ("herdr", "api", "snapshot")
TOKEN = "t" * 32
SETTING_VARIABLES = [
    "HERDR_MCP_TOKEN",
    "HERDR_MCP_PUBLIC_HOST",
    "HERDR_MCP_HOST",
    "HERDR_MCP_PORT",
    "HERDR_BIN",
    "HERDR_MCP_LOG_HEADERS",
]
INVALID_SETTINGS = [
    ("HERDR_MCP_TOKEN", None),
    ("HERDR_MCP_TOKEN", "t" * 31),
    ("HERDR_MCP_TOKEN", "t" * 16 + " " + "t" * 16),
    ("HERDR_MCP_PUBLIC_HOST", "mcp.example.com:443"),
    ("HERDR_MCP_HOST", "localhost:80"),
    ("HERDR_MCP_PORT", "0"),
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
EXPECTED_SUMMARIES = [
    {"target": "alpha", "kind": "claude", "status": "working", "workspace": "api"},
    {"target": "w1:p2", "kind": "codex", "status": "idle", "workspace": "api"},
    {"target": "beta", "kind": "claude", "status": "blocked", "workspace": "web"},
    {"target": "gamma", "kind": "codex", "status": "done", "workspace": "unknown"},
]
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
LIST_AGENTS_CALL = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "list_agents", "arguments": {}},
}


@pytest.fixture
def snapshot_json() -> dict[str, Any]:
    return {
        "id": "1",
        "result": {
            "type": "snapshot",
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
def fake_runner() -> Callable[[dict[tuple[str, ...], RunResult]], Runner]:
    def build(results: dict[tuple[str, ...], RunResult]) -> Runner:
        def run(args: list[str], timeout: float) -> RunResult:
            return results[tuple(args)]

        return run

    return build


@pytest.fixture
def snapshot_herdr(snapshot_json, fake_runner) -> Herdr:
    return Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))


@pytest.fixture
def auth_client() -> TestClient:
    stub = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"))])
    return TestClient(BearerTokenMiddleware(stub, TOKEN))


def succeeded(payload: Any) -> RunResult:
    return RunResult(exit_code=0, stdout=json.dumps(payload), stderr="")


def failed_with(code: str) -> RunResult:
    stderr = json.dumps({"error": {"code": code, "message": "synthetic failure"}})
    return RunResult(exit_code=1, stdout="", stderr=stderr)


@contextmanager
def mcp_session(herdr: Herdr) -> Iterator[tuple[TestClient, dict[str, str]]]:
    settings = Settings(
        token=TOKEN,
        public_host=None,
        host="127.0.0.1",
        port=8000,
        herdr_binary="herdr",
        log_headers=False,
    )
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(build_app(settings, herdr), base_url="http://127.0.0.1:8000") as client:
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
