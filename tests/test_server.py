import json

from conftest import LIST_AGENTS_CALL, SNAPSHOT_ARGS, mcp_session

from herdr_mcp.herdr import Herdr, RunResult
from herdr_mcp.server import AgentSummary, summarise_agents

EXPECTED_AGENTS = [
    {"target": "alpha", "kind": "claude", "status": "working", "workspace": "api"},
    {"target": "w1:p2", "kind": "codex", "status": "idle", "workspace": "api"},
    {"target": "beta", "kind": "claude", "status": "blocked", "workspace": "web"},
    {"target": "gamma", "kind": "codex", "status": "done", "workspace": "unknown"},
]


def test_list_agents_over_streamable_http_returns_json(snapshot_herdr):
    with mcp_session(snapshot_herdr) as (client, headers):
        response = client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL)

    assert response.headers["content-type"] == "application/json"
    assert response.json()["result"]["structuredContent"] == {"agents": EXPECTED_AGENTS}


def test_unlisted_host_is_rejected(snapshot_herdr):
    with mcp_session(snapshot_herdr) as (client, headers):
        response = client.post(
            "/mcp", headers={**headers, "Host": "evil.example"}, json=LIST_AGENTS_CALL
        )

    assert response.status_code == 421


def test_herdr_not_running_is_spoken_as_a_sentence(fake_runner):
    stderr = json.dumps({"error": {"code": "server_not_running", "message": "not running"}})
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(1, "", stderr)}))

    with mcp_session(herdr) as (client, headers):
        result = client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL).json()["result"]

    assert (result["isError"], result["content"][0]["text"]) == (
        True,
        "Error executing tool list_agents: herdr is not running on the server.",
    )


def test_summarise_agents_falls_back_to_pane_id_and_unknown_workspace(snapshot_herdr):
    summaries = summarise_agents(snapshot_herdr.snapshot())

    assert summaries == [AgentSummary(**agent) for agent in EXPECTED_AGENTS]
