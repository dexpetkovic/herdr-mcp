import pytest
from conftest import EXPECTED_RECORDS, SNAPSHOT_ARGS, failed_with, succeeded

from herdr_mcp.herdr import Herdr, HerdrError, RunResult, subprocess_runner


def test_snapshot_joins_agents_to_workspaces_and_tabs(snapshot_herdr):
    records = snapshot_herdr.snapshot()

    assert records == EXPECTED_RECORDS


def test_null_agents_list_is_unexpected_output(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"] = None
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == (
        "unexpected_output",
        "result.snapshot.agents",
    )


def test_status_outside_the_schema_enum_is_unexpected_output(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"][1]["agent_status"] = "paused"
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == (
        "unexpected_output",
        "result.snapshot.agents.1.agent_status",
    )


def test_null_worktree_leaves_checkout_kind_empty(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["workspaces"][0]["worktree"] = None
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    records = herdr.snapshot()

    assert records[0].is_main_checkout is None


def test_malformed_tab_without_agents_is_unexpected_output(snapshot_json, fake_runner):
    tabs = snapshot_json["result"]["snapshot"]["tabs"]
    tabs.append({"tab_id": "w2:t2", "workspace_id": "w2", "number": -1, "label": "2"})
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    with pytest.raises(HerdrError) as raised:
        herdr.snapshot()

    assert (raised.value.code, raised.value.field) == (
        "unexpected_output",
        "result.snapshot.tabs.2.number",
    )


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
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(1, "", "1" * 5000)}))

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

    assert (raised.value.code, raised.value.field) == (
        "unexpected_output",
        "result.snapshot.agents.0.tab_id",
    )


def test_binary_that_cannot_start_is_launch_failed(tmp_path):
    with pytest.raises(HerdrError) as raised:
        subprocess_runner([str(tmp_path / "missing-herdr"), "api", "snapshot"], timeout=1.0)

    assert (raised.value.code, raised.value.command) == ("launch_failed", "api snapshot")


def test_null_kind_and_name_are_empty(snapshot_json, fake_runner):
    snapshot_json["result"]["snapshot"]["agents"][0].update(agent=None, name=None)
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: succeeded(snapshot_json)}))

    record = herdr.snapshot()[0]

    assert (record.kind, record.name) == (None, None)
