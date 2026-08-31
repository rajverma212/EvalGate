"""Per-request database session for the HTTP API.

Sessions come in two flavours, because reads and writes want opposite things from a
connection.

**Read sessions** (:func:`read_session`, the overwhelming majority of traffic) ask the
backend for a *shared* connection: one the process already has open. This matters for the
libSQL/Turso backend, where opening a connection is a network handshake with the primary
costing ~150 ms locally and ~0.6-0.75 s from Vercel, versus ~0.1 ms to query a connection
that is already open. Sharing is safe for readers specifically — the libSQL driver enforces
no thread affinity and serialises concurrent use internally, and a ``SELECT`` never opens a
transaction, so no reader can leave pending state for another thread to commit. The SQLite
backend ignores the request and returns a private connection, which is correct there:
opening one is essentially free, and ``sqlite3`` connections genuinely are not safe to share
across FastAPI's threadpool.

**Write sessions** (:func:`write_session`) always get a private connection. Sharing one
across concurrent writers would let one thread's ``commit()`` commit another's
half-finished transaction, with ``rollback()`` unable to undo it. The platform depends on
multi-statement transactions — activation holds one open across the first evaluation's LLM
calls — so writers keep the isolation they have always had. They are rare and already slow,
so the handshake is noise.

``check_same_thread=False`` only disables ``sqlite3``'s thread-identity assertion; it is
safe for a private session because that session is used by exactly one request, never two
at once.
"""

from __future__ import annotations

from mrds.dashboard.data import DashboardData
from mrds.db.backends import StorageBackend, get_backend
from mrds.db.store import EvaluationStore


class ApiSession:
    """A request-scoped store + read-only data seam over one DB connection.

    Args:
        backend: The storage backend to open through, so the API never depends on a
            specific engine; tests inject an explicit one (e.g. ``SqliteBackend``).
        shared: Ask for a connection already open in this process rather than a new one.
            **Read-only callers only** — see the module docstring. Backends for which
            sharing buys nothing ignore it.
    """

    def __init__(self, backend: StorageBackend | None = None, *, shared: bool = False) -> None:
        self._db = (backend or get_backend()).connect(check_same_thread=False, shared=shared)
        self.store = EvaluationStore(self._db)
        self.data = DashboardData(self.store)

    def close(self) -> None:
        """Release the connection.

        A no-op for a shared connection, which belongs to the process rather than to this
        request — so callers can (and do) close unconditionally.
        """
        self._db.close()
