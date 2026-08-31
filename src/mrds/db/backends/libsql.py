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

**Connecting is the expensive part, so read connections are shared and kept warm.**
``libsql.connect(path, sync_url=..., auth_token=...)`` does its own network handshake with
the Turso primary every time it is given replica kwargs — measured at ~150 ms locally and
~0.6-0.75 s from Vercel, *independent* of any explicit ``.sync()``. Opening one per HTTP
request (the original design) therefore put that cost on every request, where it dominated
perceived site latency. A query on an already-open connection, by contrast, costs ~0.1 ms.

So :meth:`LibsqlBackend.connect` takes ``shared=True`` for read traffic: the first caller
opens the replica and every later caller in the same process reuses that one connection,
paying the handshake once per warm process instead of once per request. Three properties
make this safe, each verified empirically against the driver rather than assumed:

* **The driver is thread-safe.** Unlike ``sqlite3`` it enforces no thread affinity (its
  ``_check_same_thread`` is not applied), and the underlying Rust connection serialises
  concurrent use internally — 8 threads hammering one connection produced no errors and no
  lost writes. So FastAPI's threadpool can share one handle.
* **Reads cannot corrupt each other's transactions.** Under the driver's legacy
  transaction control a ``SELECT`` never opens a transaction, so a connection used only for
  reads never has pending state for another thread's ``commit()`` to capture. That is why
  sharing is offered for reads only — see the *writes* note below.
* **Freshness is the driver's job, not ours.** The shared connection is opened with
  ``sync_interval``, so libsql refreshes the replica from the primary on a background
  timer. Measured: reads stay at ~0.3 ms p50 with no periodic stalls, and a write committed
  by a *different* connection became visible in ~1.3 s. That bounds cross-instance
  staleness without any request ever paying for a sync (an explicit ``.sync()`` costs
  ~290 ms and would block whoever triggered it).

**Writes keep a private connection per caller** (``shared=False``, the default). Sharing one
connection across concurrent writers is genuinely unsafe here: with a single shared handle,
one thread's ``commit()`` commits another thread's half-finished transaction, and a
``rollback()`` can no longer undo it — reproduced directly. The platform relies on
multi-statement transactions (and, in activation, on a transaction that stays open across
the first evaluation's LLM calls), so writers get an isolated connection exactly as before.
Write endpoints are rare and already slow, so the handshake is noise there.

Note that pooling — several connections open on the same replica file — was measured and
rejected: six concurrent connections produced ``database is locked`` errors and silently
lost writes, while one shared connection did the same work 27x faster with none.

Selecting this backend is configuration only: ``MRDS_STORAGE_BACKEND=libsql``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mrds.db.backends.base import StorageBackend
from mrds.db.connection import Database
from mrds.db.errors import DbError
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

_IN_MEMORY = ":memory:"

#: Exceptions that must never be mistaken for a broken connection — they are control flow,
#: not driver failure, and swallowing them would break Ctrl-C and interpreter shutdown.
_CONTROL_FLOW = (KeyboardInterrupt, SystemExit, GeneratorExit)

#: How stale a replica may get before it is refreshed from the Turso primary. Applied two
#: ways: shared connections hand it to the driver as ``sync_interval`` (background refresh,
#: no request ever waits), private connections use it to throttle the explicit ``.sync()``
#: below. Keyed by sync_url so multiple databases in one process throttle independently.
#: Module-level (not per-backend-instance) because each write request builds a fresh
#: ``LibsqlBackend``, so the throttle must outlive any single request.
_SYNC_INTERVAL_SECONDS = 3.0
_last_synced_at: dict[str, float] = {}

#: Warm read connections, one per distinct database, reused for the life of the process.
#: ``_shared_guard`` covers only creation, so exactly one connection is opened per key even
#: if several threads race on a cold process; use of the connection itself needs no lock
#: (the driver serialises internally — see the module docstring).
_shared_guard = threading.Lock()
_shared_connections: dict[str, LibsqlDatabase] = {}


@contextmanager
def _ignoring_driver_failure(action: str) -> Iterator[None]:
    """Run a driver call that is allowed to fail because we are discarding the connection.

    Catches ``BaseException`` on purpose. The libSQL client is a Rust extension, and calling
    into a dead handle surfaces as ``pyo3_runtime.PanicException``, which derives from
    ``BaseException`` rather than ``Exception`` — so a plain ``except Exception`` misses it
    entirely. Genuine control flow is re-raised.
    """
    try:
        yield
    except _CONTROL_FLOW:
        raise
    except BaseException as exc:  # noqa: BLE001 - see above; the connection is being dropped
        logger.debug("Ignoring libSQL failure while %s: %s", action, exc)


def _shared_key(database_path: str, sync_url: str | None) -> str:
    return f"{database_path}|{sync_url or ''}"


def reset_shared_connections() -> None:
    """Close and forget every cached shared connection.

    For test teardown and any caller that needs the next ``connect(shared=True)`` to open a
    genuinely new connection (a rotated auth token, a repointed replica path). Not needed in
    normal operation: shared connections are meant to live as long as the process.
    """
    with _shared_guard:
        for db in _shared_connections.values():
            with _ignoring_driver_failure("resetting shared connections"):
                db.close(force=True)
        _shared_connections.clear()


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

    Reuses :class:`Database`'s ``bootstrap`` / ``transaction`` — they operate only through
    the connection surface, which :class:`_Connection` satisfies.

    Args:
        raw_conn: An open driver connection.
        path: The replica/database file path, for logging and pragma selection.
        shared: Marks a process-wide connection handed to many callers. Such a connection
            outlives any one of them, so :meth:`close` is a no-op for it.
    """

    def __init__(self, raw_conn: Any, *, path: str, shared: bool = False) -> None:
        self._path = path
        self._shared = shared
        self._conn = _Connection(raw_conn)  # type: ignore[assignment] - duck-typed connection
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != _IN_MEMORY:
            self._conn.execute("PRAGMA journal_mode = WAL")

    @property
    def is_shared(self) -> bool:
        """Whether this connection is process-wide and therefore not the caller's to close."""
        return self._shared

    def is_usable(self) -> bool:
        """Whether this connection still answers queries.

        A shared connection outlives the request that opened it, so it can be found dead
        later — a serverless instance frozen between invocations and thawed, a dropped
        replica session, a rotated auth token. The probe is a local read costing well under
        a millisecond, which is nothing against the ~150-750 ms it guards.
        """
        try:
            self._conn.execute("SELECT 1").fetchone()
        except _CONTROL_FLOW:
            raise
        except BaseException:  # noqa: BLE001 - any driver failure means "reopen"; see helper
            return False
        return True

    def close(self, *, force: bool = False) -> None:
        """Close the connection — unless it is shared, which callers must not close.

        A shared connection is borrowed: every request calls ``close()`` on the session that
        wraps it, and closing for real would tear the connection out from under every other
        in-flight caller. ``force=True`` is the owner's escape hatch (see
        :func:`reset_shared_connections`).
        """
        if self._shared and not force:
            return
        self._conn.close()


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

    def connect(self, *, check_same_thread: bool = True, shared: bool = False) -> Database:
        """Open a libSQL database.

        Args:
            check_same_thread: Ignored — libSQL enforces no thread affinity. Accepted for
                interface parity, per :class:`StorageBackend`.
            shared: Reuse (and, on first call, create) this process's warm connection for
                this database instead of opening a new one. Only safe for **read-only**
                callers; see the module docstring for why writers must not share.
        """
        if shared:
            return self._shared_connection()
        return self._open(shared=False)

    def _shared_connection(self) -> Database:
        """This process's warm connection for this database, opened on first use.

        Reopens transparently if the cached connection has died, so one bad handle cannot
        poison every subsequent request for the life of the process.
        """
        key = _shared_key(self._database_path, self._sync_url)
        cached = _shared_connections.get(key)
        if cached is not None and cached.is_usable():
            return cached
        with _shared_guard:
            # Re-check under the guard: another thread may have opened or replaced it while
            # we waited, in which case its connection is the one to use.
            cached = _shared_connections.get(key)
            if cached is not None:
                if cached.is_usable():
                    return cached
                logger.warning(
                    "Shared libSQL connection to %s is no longer usable; reopening",
                    self._database_path,
                )
                with _ignoring_driver_failure("closing a dead shared connection"):
                    cached.close(force=True)
                del _shared_connections[key]
            fresh = self._open(shared=True)
            _shared_connections[key] = fresh
            return fresh

    def _open(self, *, shared: bool) -> LibsqlDatabase:
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
            if shared:
                # A shared connection is long-lived, so hand freshness to the driver: it
                # refreshes the replica on a background timer instead of any request paying
                # for an explicit (~290 ms) sync.
                kwargs["sync_interval"] = _SYNC_INTERVAL_SECONDS

        raw = libsql.connect(self._database_path, **kwargs)
        db = LibsqlDatabase(raw, path=self._database_path, shared=shared)
        if self._sync_url is not None and not shared:
            # Private connections have no background timer, so pull remote changes here —
            # throttled, because a sync is a real network round-trip to the primary.
            now = time.monotonic()
            last = _last_synced_at.get(self._sync_url, 0.0)
            if now - last >= _SYNC_INTERVAL_SECONDS:
                db.connection.sync()  # type: ignore[attr-defined] - pull remote changes
                _last_synced_at[self._sync_url] = now
        db.bootstrap()
        logger.info(
            "Opened %s libSQL database at %s%s",
            "shared" if shared else "private",
            self._database_path,
            f" (replica of {self._sync_url})" if self._sync_url else "",
        )
        return db
