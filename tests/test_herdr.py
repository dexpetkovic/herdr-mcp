import json

import pytest
from conftest import SNAPSHOT_ARGS, succeeded

from herdr_mcp.herdr import AgentRecord, Herdr, HerdrError, RunResult


def test_snapshot_joins_agents_to_workspaces_and_tabs(snapshot_herdr):
    records = snapshot_herdr.snapshot()

    assert records == [
        AgentRecord("alpha", "w1:p1", "claude", "working", "api", True, 1, 2),
        AgentRecord(None, "w1:p2", "codex", "idle", "api", True, 1, 2),
        AgentRecord("beta", "w2:p1", "claude", "blocked", "web", False, 1, 1),
        AgentRecord("gamma", "w3:p1", "codex", "done", None, None, None, 1),
    ]


def test_null_agents_list_is_unexpected_output(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"] = None
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == ("unexpected_output", "agents")


def test_herdr_error_code_comes_from_stderr_json(fake_runner):
    stderr = json.dumps({"error": {"code": "server_not_running", "message": "not running"}})
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(1, "", stderr)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.command, raised.value.exit_code) == (
        "server_not_running",
        "api snapshot",
        1,
    )


def test_stderr_that_is_not_json_is_unreadable_error(fake_runner):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(1, "", "panic")}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert raised.value.code == "unreadable_error"


def test_exit_code_two_is_invalid_syntax(fake_runner):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(2, "", "usage: herdr")}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.exit_code) == ("invalid_syntax", 2)


def test_stdout_without_snapshot_is_unexpected_output(fake_runner):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded({"id": "1", "result": {}})}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert raised.value.code == "unexpected_output"


def test_numeric_tab_id_is_unexpected_output(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"][0]["tab_id"] = 7
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == ("unexpected_output", "tab_id")
