import pytest
from conftest import SNAPSHOT_ARGS, failed_with, succeeded

from herdr_mcp.herdr import AgentRecord, Herdr, HerdrError, RunResult, subprocess_runner


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


def test_null_worktree_leaves_checkout_kind_empty(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["workspaces"][0]["worktree"] = None
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    records = herdr.snapshot()

    assert records[0].is_main_checkout is None


def test_herdr_error_code_comes_from_stderr_json(fake_runner):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: failed_with("server_not_running")}))

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

    assert (raised.value.code, raised.value.field) == ("unexpected_output", "result.snapshot")


def test_numeric_tab_id_is_unexpected_output(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"][0]["tab_id"] = 7
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == ("unexpected_output", "tab_id")


def test_binary_that_cannot_start_is_launch_failed(tmp_path):
    with pytest.raises(HerdrError) as raised:
        subprocess_runner([str(tmp_path / "missing-herdr"), "api", "snapshot"], timeout=1.0)

    assert (raised.value.code, raised.value.command) == ("launch_failed", "api snapshot")
