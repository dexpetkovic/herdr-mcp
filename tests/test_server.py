from conftest import EXPECTED_SUMMARIES, LIST_AGENTS_CALL, SNAPSHOT_ARGS, failed_with, mcp_session

from herdr_mcp.herdr import Herdr
from herdr_mcp.server import AgentSummary, summarise_agents


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
