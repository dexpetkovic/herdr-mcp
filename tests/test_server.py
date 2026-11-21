import logging

import pytest
from conftest import (
    EXPECTED_SUMMARIES,
    INITIALIZE_REQUEST,
    LIST_AGENTS_CALL,
    MESSAGE,
    PROMPT_FAILURE_SENTENCES,
    SCREEN_TEXT,
    SEND_MESSAGE_REFUSALS,
    SNAPSHOT_ARGS,
    TRIMMED_SCREEN,
    failed_with,
    mcp_session,
    orchestrator_snapshot,
    prompt_args,
    screen_read_args,
    succeeded,
    tool_call,
)

from herdr_mcp.herdr import Herdr, RunResult
from herdr_mcp.server import (
    SERVER_INSTRUCTIONS,
    AgentSummary,
    summarise_agents,
    trim_screen_text,
)


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


def test_unnamed_agent_alone_in_tab_one_of_the_main_checkout_is_marked_orchestrator(
    snapshot_json, fake_runner
):
    snapshot = orchestrator_snapshot(snapshot_json, named=False)
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot)}))

    assert summarise_agents(herdr.snapshot())[0].model_dump() == {
        "target": "w1:p1",
        "kind": "claude",
        "status": "idle",
        "workspace": "api",
        "orchestrator": True,
    }


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


def test_trim_screen_text_drops_trailing_spaces_and_repeated_blank_lines():
    assert trim_screen_text(SCREEN_TEXT) == TRIMMED_SCREEN


def test_trim_screen_text_keeps_the_last_4000_characters():
    assert trim_screen_text("x" * 3000 + "\n" + "y" * 3000) == "x" * 999 + "\n" + "y" * 3000


def test_trim_screen_text_names_an_empty_screen():
    assert trim_screen_text("\n  \n") == "The screen is empty."


@pytest.mark.parametrize("target", ["alpha", "w1:p2"])
def test_get_agent_activity_returns_the_trimmed_screen(fake_runner, caplog, target):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    herdr = Herdr("herdr", fake_runner({screen_read_args(target): RunResult(0, SCREEN_TEXT, "")}))

    with mcp_session(herdr) as (client, headers):
        call = tool_call("get_agent_activity", {"agent": target})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert result["structuredContent"] == {"target": target, "screen": TRIMMED_SCREEN}
    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [("get_agent_activity", "ok")]


def test_get_agent_activity_for_a_missing_agent_says_none_matches(fake_runner, caplog):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    herdr = Herdr("herdr", fake_runner({screen_read_args("delta"): failed_with("agent_not_found")}))

    with mcp_session(herdr) as (client, headers):
        call = tool_call("get_agent_activity", {"agent": "delta"})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert (result["isError"], result["content"]) == (
        True,
        [{"type": "text", "text": "No running agent matches that target."}],
    )
    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [
        ("get_agent_activity", "error")
    ]


def test_get_agent_activity_rejects_an_option_shaped_target(fake_runner):
    with mcp_session(Herdr("herdr", fake_runner({}))) as (client, headers):
        call = tool_call("get_agent_activity", {"agent": "-x"})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert (result["isError"], result["content"]) == (
        True,
        [{"type": "text", "text": "That is not an agent name or pane id."}],
    )


@pytest.mark.parametrize(
    ("agent", "text", "snapshot_changes", "expected_calls", "sentence"), SEND_MESSAGE_REFUSALS
)
def test_send_message_refuses_without_prompting(
    snapshot_json, fake_runner, caplog, agent, text, snapshot_changes, expected_calls, sentence
):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    snapshot = orchestrator_snapshot(snapshot_json, **snapshot_changes)
    runner = fake_runner({SNAPSHOT_ARGS: succeeded(snapshot)})

    with mcp_session(Herdr("herdr", runner)) as (client, headers):
        call = tool_call("send_message", {"agent": agent, "text": text})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert (result["isError"], result["content"]) == (True, [{"type": "text", "text": sentence}])
    assert runner.calls == expected_calls
    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [("send_message", "error")]


@pytest.mark.parametrize(("prompt_result", "sentence"), PROMPT_FAILURE_SENTENCES)
def test_send_message_speaks_each_prompt_failure(
    snapshot_json, fake_runner, prompt_result, sentence
):
    runner = fake_runner(
        {
            SNAPSHOT_ARGS: succeeded(orchestrator_snapshot(snapshot_json)),
            prompt_args("alpha", MESSAGE): prompt_result,
        }
    )

    with mcp_session(Herdr("herdr", runner)) as (client, headers):
        call = tool_call("send_message", {"agent": "alpha", "text": MESSAGE})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert (result["isError"], result["content"]) == (True, [{"type": "text", "text": sentence}])


@pytest.mark.parametrize("status", ["idle", "done"])
def test_send_message_prompts_a_ready_orchestrator(snapshot_json, fake_runner, caplog, status):
    caplog.set_level(logging.INFO, logger="herdr_mcp")
    text = "-x run the tests"
    runner = fake_runner(
        {
            SNAPSHOT_ARGS: succeeded(orchestrator_snapshot(snapshot_json, status=status)),
            prompt_args("alpha", text): RunResult(0, "", ""),
        }
    )

    with mcp_session(Herdr("herdr", runner)) as (client, headers):
        call = tool_call("send_message", {"agent": "alpha", "text": text})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert result["structuredContent"] == {"target": "alpha", "sent": True}
    assert runner.calls == [SNAPSHOT_ARGS, prompt_args("alpha", text)]
    records = [record for record in caplog.records if record.getMessage() == "tool call"]
    assert [(record.tool, record.outcome) for record in records] == [("send_message", "ok")]


def test_send_message_rejects_a_text_over_2000_characters(fake_runner):
    runner = fake_runner({})

    with mcp_session(Herdr("herdr", runner)) as (client, headers):
        call = tool_call("send_message", {"agent": "alpha", "text": "x" * 2001})
        result = client.post("/mcp", headers=headers, json=call).json()["result"]

    assert result["isError"] is True
    assert runner.calls == []
