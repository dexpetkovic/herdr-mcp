"""The conversation history: messages delivered to orchestrators and their one-line recaps."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

MAX_EXCHANGES = 30
MAX_EXCHANGE_AGE = timedelta(days=7)
# The reply wait leaves a short budget for a SQLite lock.
LOCK_TIMEOUT_SECONDS = 0.5
CREATE_TABLES = (
    "CREATE TABLE IF NOT EXISTS exchanges (id INTEGER PRIMARY KEY, "
    "exchange_id TEXT NOT NULL UNIQUE, sent_at TEXT NOT NULL, "
    "orchestrator TEXT NOT NULL, message TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS recaps (exchange_id TEXT PRIMARY KEY, "
    "saved_at TEXT NOT NULL, recap TEXT NOT NULL)",
)
KEPT_EXCHANGE_CONDITION = (
    "sent_at >= :oldest_kept AND id IN (SELECT id FROM exchanges "
    "WHERE sent_at >= :oldest_kept ORDER BY id DESC LIMIT :max_exchanges)"
)
# Recaps go with their message. A recap without a message row waits for it until it expires.
DELETE_OUTDATED_ROWS = (
    "DELETE FROM recaps WHERE exchange_id IN (SELECT exchange_id FROM exchanges "
    f"WHERE NOT ({KEPT_EXCHANGE_CONDITION}))",
    f"DELETE FROM exchanges WHERE NOT ({KEPT_EXCHANGE_CONDITION})",
    "DELETE FROM recaps WHERE saved_at < :oldest_kept",
)
SELECT_RECENT_EXCHANGES = (
    "SELECT exchanges.exchange_id, sent_at, orchestrator, message, recap FROM exchanges "
    "LEFT JOIN recaps ON recaps.exchange_id = exchanges.exchange_id "
    "WHERE sent_at >= :oldest_kept ORDER BY id"
)


class Exchange(BaseModel):
    exchange_id: str
    sent_at: str
    orchestrator: str
    message: str
    recap: str | None


class HistoryUnavailable(Exception):
    """The history store cannot be read or written. The cause holds the backend error."""


class ConversationHistory(Protocol):
    def record_exchange(self, exchange_id: str, orchestrator: str, message: str) -> None: ...

    def save_recap(self, exchange_id: str, recap: str) -> None: ...

    def recent_exchanges(self) -> list[Exchange]: ...


class SqliteConversationHistory:
    """Timestamps are UTC ISO 8601 to the second, so string order is time order."""

    def __init__(self, path: Path, clock: Callable[[], datetime]) -> None:
        self._path = path
        self._clock = clock
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise HistoryUnavailable(str(path)) from error
        with self._transaction(begin_immediately=True) as connection:
            for create_table_statement in CREATE_TABLES:
                connection.execute(create_table_statement)
            self._delete_outdated_rows(connection)

    def record_exchange(self, exchange_id: str, orchestrator: str, message: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO exchanges (exchange_id, sent_at, orchestrator, message) "
                "VALUES (?, ?, ?, ?)",
                (exchange_id, _timestamp(self._clock()), orchestrator, message),
            )
            self._delete_outdated_rows(connection)

    def save_recap(self, exchange_id: str, recap: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO recaps (exchange_id, saved_at, recap) VALUES (?, ?, ?)",
                (exchange_id, _timestamp(self._clock()), recap),
            )

    def recent_exchanges(self) -> list[Exchange]:
        with self._transaction() as connection:
            exchange_rows = connection.execute(
                SELECT_RECENT_EXCHANGES, {"oldest_kept": self._oldest_kept_timestamp()}
            ).fetchall()
        return [
            Exchange(
                exchange_id=exchange_id,
                sent_at=sent_at,
                orchestrator=orchestrator,
                message=message,
                recap=recap,
            )
            for exchange_id, sent_at, orchestrator, message, recap in exchange_rows
        ]

    def _delete_outdated_rows(self, connection: sqlite3.Connection) -> None:
        parameters = {"oldest_kept": self._oldest_kept_timestamp(), "max_exchanges": MAX_EXCHANGES}
        for delete_statement in DELETE_OUTDATED_ROWS:
            connection.execute(delete_statement, parameters)

    def _oldest_kept_timestamp(self) -> str:
        return _timestamp(self._clock() - MAX_EXCHANGE_AGE)

    @contextmanager
    def _transaction(self, begin_immediately: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self._path, timeout=LOCK_TIMEOUT_SECONDS)) as connection:
                with connection:
                    if begin_immediately:
                        connection.execute("BEGIN IMMEDIATE")
                    yield connection
        except (sqlite3.Error, OSError) as error:
            raise HistoryUnavailable(str(self._path)) from error


def _timestamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")
