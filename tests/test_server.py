import logging

from conftest import (
    EXPECTED_SUMMARIES,
    INITIALIZE_REQUEST,
    LIST_AGENTS_CALL,
    SNAPSHOT_ARGS,
    failed_with,
    mcp_session,
    succeeded,
)

from herdr_mcp.herdr import Herdr
from herdr_mcp.server import SERVER_INSTRUCTIONS, AgentSummary, summarise_agents


def test_list_agents_over_streamable_http_returns_json(snapshot_herdr):
    with mcp_session(snapshot_herdr) as (client, headers):
        response = client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL)

    assert response.headers["content-type"] == "application/json"
    assert response.json()["result"]["structuredContent"] == {"agents": EXPECTED_SUMMARIES}


def test_unlisted_host_is_rejected(snapshot_herdr):
    with mcp_session(snapshot_herdr) as (client, headers):
        response = client.post(
            "/mcp", headers={**headers, "Host": "evil.example"}, json=LIST_AGENTS_CALL
        )

    assert response.status_code == 421


def test_herdr_not_running_is_spoken_as_one_sentence(fake_runner):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: failed_with("server_not_running")}))

    with mcp_session(herdr) as (client, headers):
        result = client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL).json()["result"]

    assert (result["isError"], result["content"]) == (
        True,
        [{"type": "text", "text": "herdr is not running on the server."}],
    )


def test_summarise_agents_falls_back_to_pane_id_and_unknown_workspace(snapshot_herdr):
    summaries = summarise_agents(snapshot_herdr.snapshot())

    assert summaries == [AgentSummary(**summary) for summary in EXPECTED_SUMMARIES]


def test_summary_without_kind_says_unknown(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"][0]["agent"] = None
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    assert summarise_agents(herdr.snapshot())[0].kind == "unknown"


def test_initialize_returns_server_instructions(snapshot_herdr):
    with mcp_session(snapshot_herdr) as (client, headers):
        del headers["Mcp-Session-Id"]
        result = client.post("/mcp", headers=headers, json=INITIALIZE_REQUEST).json()["result"]

    assert result["instructions"] == SERVER_INSTRUCTIONS


def test_list_agents_logs_one_tool_call(snapshot_herdr, caplog):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    with mcp_session(snapshot_herdr) as (client, headers):
        client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL)

    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [("list_agents", "ok")]
    assert isinstance(records[0].duration_ms, int)
    assert records[0].duration_ms >= 0


def test_failing_list_agents_logs_an_error_outcome(failing_herdr, caplog):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    with mcp_session(failing_herdr) as (client, headers):
        client.post("/mcp", headers=headers, json=LIST_AGENTS_CALL)

    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [("list_agents", "error")]
