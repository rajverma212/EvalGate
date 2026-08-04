"""libSQL / Turso storage backend — a second engine behind :class:`StorageBackend`.

libSQL is SQLite-compatible on the wire and speaks the same SQL EvalOS already uses, so
the schema, migrations, repositories, and every layer above them run unchanged. Two modes:

* **local file** (default) — a libSQL database file at ``settings.database_path``; offline,
  used for local dev and the test suite.
* **Turso embedded replica** — when ``settings.libsql_sync_url`` is set, a local replica is
  synced from a remote Turso primary (``auth_token`` for auth). Reads are local; writes go
  to the primary. This is the durable, multi-instance option a serverless deploy needs.

One adaptation is required: the libSQL driver returns rows as **plain tuples** and does not
support ``row_factory``, whereas EvalOS's repositories read columns by name and call
``dict(row)`` (relying on ``sqlite3.Row``). :class:`_Connection` wraps the driver connection
and, using each cursor's ``description``, yields :class:`_Row` objects that support integer
and string indexing and the mapping protocol — so no caller above the backend changes.

**Sync is throttled, not per-request.** Every ``EvaluationStore`` operation opens a fresh
connection (see ``ApiSession``), and an embedded replica's ``.sync()`` is a real network
round-trip to the Turso primary — calling it unconditionally on every connect turned every
API request into a ~1s wait, dominating perceived site latency. But a fresh
``libsql.connect()`` against an *already-synced* local replica file is a fast local file
open (~0.1s), and — proven empirically — any connection opened against that same local file
immediately sees writes committed by another connection to it, with **no sync required**:
writes land in the local file directly, not only on the remote primary. So ``.sync()`` is
only actually needed to pull in changes made by a *different process* (another serverless
instance, a different region). We throttle it to at most once per
``_SYNC_INTERVAL_SECONDS`` per process — bounding cross-instance staleness to a few seconds
(imperceptible in practice) while making same-instance traffic (the overwhelming majority of
requests) pay zero network cost per connect.

Selecting this backend is configuration only: ``MRDS_STORAGE_BACKEND=libsql``.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from mrds.db.backends.base import StorageBackend
from mrds.db.connection import Database
from mrds.db.errors import DbError
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

_IN_MEMORY = ":memory:"

#: Minimum time between real ``.sync()`` network round-trips to the Turso primary, per
#: process/sync_url. Keyed by sync_url so multiple databases in one process throttle
#: independently. Module-level (not per-backend-instance) because each API request builds
#: a fresh ``LibsqlBackend``/connection, so the throttle must outlive any single request.
_SYNC_INTERVAL_SECONDS = 3.0
_last_synced_at: dict[str, float] = {}


class _Row:
    """A ``sqlite3.Row``-like wrapper over a libSQL tuple row.

    Supports integer indexing (``row[0]``), string indexing (``row["col"]``), and the
    mapping protocol (``dict(row)`` via :meth:`keys` + ``__getitem__``).
    """

    __slots__ = ("_cols", "_map", "_vals")

    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._cols = columns
        self._vals = values
        self._map = dict(zip(columns, values, strict=False))

    def __getitem__(self, key: int | str) -> Any:
        return self._vals[key] if isinstance(key, int) else self._map[key]

    def keys(self) -> list[str]:
        return list(self._cols)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)


class _Cursor:
    """Wraps a libSQL cursor so fetched rows come back as :class:`_Row`."""

    __slots__ = ("_cur",)

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    @property
    def lastrowid(self) -> int | None:
        return self._cur.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self) -> Any:
        return self._cur.description

    def _columns(self) -> list[str]:
        desc = self._cur.description
        return [col[0] for col in desc] if desc else []

    def fetchone(self) -> _Row | None:
        row = self._cur.fetchone()
        return _Row(self._columns(), row) if row is not None else None

    def fetchall(self) -> list[_Row]:
        columns = self._columns()
        return [_Row(columns, row) for row in self._cur.fetchall()]

    def __iter__(self) -> Iterator[_Row]:
        columns = self._columns()
        for row in self._cur:
            yield _Row(columns, row)


class _Connection:
    """Adapts a libSQL connection to the ``sqlite3.Connection`` surface EvalOS uses.

    Forwards execution to the driver but returns name-addressable rows (see module
    docstring). Only the methods the DB layer actually calls are exposed.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> _Cursor:
        return _Cursor(self._conn.execute(sql, parameters))

    def executemany(self, sql: str, seq_of_parameters: Sequence[Sequence[Any]]) -> _Cursor:
        return _Cursor(self._conn.executemany(sql, list(seq_of_parameters)))

    def executescript(self, script: str) -> Any:
        return self._conn.executescript(script)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def sync(self) -> None:
        """Pull the latest state from the Turso primary (no-op for a local file)."""
        sync = getattr(self._conn, "sync", None)
        if callable(sync):
            sync()


class LibsqlDatabase(Database):
    """A :class:`Database` backed by a libSQL connection (via the row-adapter).

    Reuses :class:`Database`'s ``bootstrap`` / ``transaction`` / ``close`` — they operate
    only through the connection surface, which :class:`_Connection` satisfies.
    """

    def __init__(self, raw_conn: Any, *, path: str) -> None:
        self._path = path
        self._conn = _Connection(raw_conn)  # type: ignore[assignment] - duck-typed connection
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != _IN_MEMORY:
            self._conn.execute("PRAGMA journal_mode = WAL")


class LibsqlBackend(StorageBackend):
    """Opens a libSQL database — a local file, or a Turso embedded replica."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        sync_url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self._database_path = str(database_path) if database_path is not None else _IN_MEMORY
        self._sync_url = sync_url
        self._auth_token = auth_token

    @property
    def name(self) -> str:
        return "libsql"

    def connect(self, *, check_same_thread: bool = True) -> Database:
        # check_same_thread does not apply to libSQL (it has no sqlite3 thread-affinity
        # assertion); accepted for interface parity and ignored, per StorageBackend.
        try:
            import libsql
        except ModuleNotFoundError as exc:
            raise DbError(
                "storage_backend is 'libsql' but the 'libsql' package is not installed; "
                "install the optional extra: pip install '.[libsql]'"
            ) from exc

        if self._database_path != _IN_MEMORY and self._sync_url is None:
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)

        kwargs: dict[str, Any] = {}
        if self._sync_url is not None:
            kwargs["sync_url"] = self._sync_url
            if self._auth_token is not None:
                kwargs["auth_token"] = self._auth_token

        raw = libsql.connect(self._database_path, **kwargs)
        db = LibsqlDatabase(raw, path=self._database_path)
        if self._sync_url is not None:
            now = time.monotonic()
            last = _last_synced_at.get(self._sync_url, 0.0)
            if now - last >= _SYNC_INTERVAL_SECONDS:
                db.connection.sync()  # type: ignore[attr-defined] - pull remote changes
                _last_synced_at[self._sync_url] = now
        db.bootstrap()
        logger.info(
            "Opened libSQL database at %s%s",
            self._database_path,
            f" (replica of {self._sync_url})" if self._sync_url else "",
        )
        return db
