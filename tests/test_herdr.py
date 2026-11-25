import pytest
from conftest import (
    EXPECTED_RECORDS,
    READ_ALPHA_ARGS,
    SCREEN_TEXT,
    SNAPSHOT_ARGS,
    UNREADABLE_STDERR,
    UNSETTLED_PROMPT_RESULTS,
    failed_with,
    prompt_args,
    settled_as,
    succeeded,
)

from herdr_mcp.herdr.client import Herdr, RunResult, subprocess_runner
from herdr_mcp.herdr.exceptions import HerdrError


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


@pytest.mark.parametrize("stderr", UNREADABLE_STDERR.values(), ids=UNREADABLE_STDERR.keys())
def test_stderr_without_herdr_error_json_is_unreadable_error(fake_runner, stderr):
    herdr = Herdr("herdr", fake_runner({SNAPSHOT_ARGS: RunResult(1, "", stderr)}))

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


def test_read_screen_returns_the_visible_screen_unchanged(fake_runner):
    herdr = Herdr("herdr", fake_runner({READ_ALPHA_ARGS: RunResult(0, SCREEN_TEXT, "")}))

    assert herdr.read_screen("alpha") == SCREEN_TEXT


def test_prompt_waits_for_the_turn_and_returns_the_settled_status(fake_runner):
    runner = fake_runner({prompt_args("alpha", "run the tests"): settled_as("done")})

    status = Herdr("herdr", runner).prompt("alpha", "run the tests", 30000)

    assert (status, runner.calls, runner.timeouts) == (
        "done",
        [prompt_args("alpha", "run the tests")],
        [35.0],
    )


def test_prompt_without_waiting_returns_the_status_at_submission(fake_runner):
    runner = fake_runner({prompt_args("alpha", "run the tests", wait=False): settled_as("working")})

    status = Herdr("herdr", runner).prompt("alpha", "run the tests", None)

    assert (status, runner.calls, runner.timeouts) == (
        "working",
        [("herdr", "agent", "prompt", "alpha", "run the tests")],
        [10.0],
    )


@pytest.mark.parametrize(("prompt_result", "field"), UNSETTLED_PROMPT_RESULTS)
def test_prompt_without_a_settled_status_is_unexpected_output(fake_runner, prompt_result, field):
    runner = fake_runner({prompt_args("alpha", "run the tests"): prompt_result})

    with pytest.raises(HerdrError) as raised:
        Herdr("herdr", runner).prompt("alpha", "run the tests", 30000)

    error = raised.value
    assert (error.code, error.command, error.exit_code, error.field) == (
        "unexpected_output",
        "agent prompt",
        0,
        field,
    )


def test_failed_prompt_names_only_the_operation(fake_runner):
    runner = fake_runner({prompt_args("alpha", "run the tests"): failed_with("agent_blocked")})

    with pytest.raises(HerdrError) as raised:
        Herdr("herdr", runner).prompt("alpha", "run the tests", 30000)

    assert (raised.value.code, raised.value.command) == ("agent_blocked", "agent prompt")


def test_prompt_that_cannot_launch_names_only_the_operation(tmp_path):
    args = [str(tmp_path / "missing-herdr"), "agent", "prompt", "alpha", "synthetic secret"]

    with pytest.raises(HerdrError) as raised:
        subprocess_runner(args, timeout=1.0)

    assert (raised.value.code, raised.value.command) == ("launch_failed", "agent prompt")
