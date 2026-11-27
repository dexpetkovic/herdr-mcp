import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from conftest import (
    FIRST_EXCHANGE_ID,
    SECOND_EXCHANGE_ID,
    count_history_table_rows,
    numbered_exchange_id,
)

from herdr_mcp.history import Exchange, HistoryUnavailable, SqliteConversationHistory


def test_recent_exchanges_returns_messages_oldest_first_with_their_recaps(history):
    history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")
    history.record_exchange(SECOND_EXCHANGE_ID, "beta", "deploy it")
    history.save_recap(FIRST_EXCHANGE_ID, "The tests passed.")

    exchanges = history.recent_exchanges()

    assert exchanges == [
        Exchange(
            exchange_id=FIRST_EXCHANGE_ID,
            sent_at="2026-11-27T08:00:00+00:00",
            orchestrator="alpha",
            message="run the tests",
            recap="The tests passed.",
        ),
        Exchange(
            exchange_id=SECOND_EXCHANGE_ID,
            sent_at="2026-11-27T08:00:00+00:00",
            orchestrator="beta",
            message="deploy it",
            recap=None,
        ),
    ]


def test_recap_saved_before_its_message_is_recorded_joins_the_message(history):
    history.save_recap(FIRST_EXCHANGE_ID, "The tests passed.")
    history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")

    recaps = [exchange.recap for exchange in history.recent_exchanges()]

    assert recaps == ["The tests passed."]


def test_history_keeps_the_newest_30_exchanges(history):
    for number in range(1, 32):
        history.record_exchange(numbered_exchange_id(number), "alpha", f"message {number}")

    exchange_ids = [exchange.exchange_id for exchange in history.recent_exchanges()]

    assert exchange_ids == [numbered_exchange_id(number) for number in range(2, 32)]


def test_recap_of_an_evicted_exchange_is_deleted_with_it(history, history_path):
    for number in range(1, 32):
        history.record_exchange(numbered_exchange_id(number), "alpha", f"message {number}")
        history.save_recap(numbered_exchange_id(number), f"recap {number}")

    with closing(sqlite3.connect(history_path)) as connection:
        stored_recaps = [row[0] for row in connection.execute("SELECT recap FROM recaps")]

    assert sorted(stored_recaps) == sorted(f"recap {number}" for number in range(2, 32))


def test_expired_exchange_does_not_count_against_the_limit(history, clock):
    for number in range(1, 31):
        history.record_exchange(numbered_exchange_id(number), "alpha", f"message {number}")
    history.save_recap(numbered_exchange_id(2), "recap 2")
    clock.now -= timedelta(days=8)
    history.record_exchange(numbered_exchange_id(31), "alpha", "message 31")
    clock.now += timedelta(days=8)
    history.record_exchange(numbered_exchange_id(32), "alpha", "message 32")

    exchanges = history.recent_exchanges()

    assert [exchange.exchange_id for exchange in exchanges] == [
        numbered_exchange_id(number) for number in [*range(2, 31), 32]
    ]
    assert exchanges[0].recap == "recap 2"


def test_recap_saved_late_expires_with_its_message(history, history_path, clock):
    history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")
    clock.now += timedelta(days=6)
    history.save_recap(FIRST_EXCHANGE_ID, "The tests passed.")
    clock.now += timedelta(days=2)

    SqliteConversationHistory(history_path, clock)

    assert count_history_table_rows(history_path, "recaps") == 0


def test_exchanges_older_than_seven_days_are_hidden_and_deleted_at_startup(
    history, history_path, clock
):
    history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")
    history.save_recap(FIRST_EXCHANGE_ID, "The tests passed.")
    clock.now += timedelta(days=8)

    exchanges = history.recent_exchanges()
    SqliteConversationHistory(history_path, clock)

    assert exchanges == []
    assert (
        count_history_table_rows(history_path, "exchanges"),
        count_history_table_rows(history_path, "recaps"),
    ) == (0, 0)


def test_exchange_exactly_seven_days_old_is_kept(history, clock):
    history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")
    clock.now += timedelta(days=7)

    exchange_ids = [exchange.exchange_id for exchange in history.recent_exchanges()]

    assert exchange_ids == [FIRST_EXCHANGE_ID]


def test_record_exchange_on_a_locked_file_raises_history_unavailable(history, history_path):
    with closing(sqlite3.connect(history_path, isolation_level=None)) as other_writer:
        other_writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(HistoryUnavailable):
            history.record_exchange(FIRST_EXCHANGE_ID, "alpha", "run the tests")


def test_store_in_a_read_only_directory_fails_at_startup(tmp_path, clock):
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(HistoryUnavailable):
            SqliteConversationHistory(tmp_path / "history.sqlite3", clock)
    finally:
        tmp_path.chmod(0o700)


def test_read_only_existing_store_fails_at_startup(history, history_path, clock):
    history_path.chmod(0o400)

    with pytest.raises(HistoryUnavailable):
        SqliteConversationHistory(history_path, clock)
