"""Storage backend abstraction — the seam that decouples EvalOS from one engine.

A :class:`StorageBackend` is a connection factory: given configuration it opens a
connected, schema-bootstrapped :class:`~mrds.db.connection.Database` for a single
storage engine. SQLite is the only backend today; libSQL/Turso, a persistent
SQLite host, or PostgreSQL can be added later as additional implementations.

Everything above the persistence layer — the store, repositories, evaluation
engine, regression detector, reporting, dashboard, CLI, and HTTP API — depends
only on this interface and the :class:`Database` it returns, never on the engine
itself. Selecting a backend is therefore a **configuration** change (which backend
the factory builds), not a code change anywhere else in EvalOS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mrds.db.connection import Database


class StorageBackend(ABC):
    """A configuration-selected provider of database connections for EvalOS."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for the backend (e.g. ``"sqlite"``); used in logs."""

    @abstractmethod
    def connect(self, *, check_same_thread: bool = True, shared: bool = False) -> Database:
        """Open a connected, schema-bootstrapped :class:`Database`.

        ``check_same_thread`` is forwarded for engines (SQLite) that enforce connection
        thread-affinity; backends to which it does not apply may ignore it. The returned
        :class:`Database` is the single contract all backends honour, so callers never
        branch on which engine is in use.

        Args:
            check_same_thread: See above.
            shared: A **hint** that the caller is read-only and would accept a connection
                already open in this process, so an engine for which connecting is
                expensive (libSQL against a remote Turso primary) can keep one warm rather
                than pay a network handshake per caller. Backends may ignore it and return
                a private connection; SQLite does, since opening is already cheap and its
                connections are not safe to share across threads.

        Returns:
            A connection the caller **owns and must close** — except when it asked for
            ``shared=True`` and the backend honoured it, in which case the connection
            belongs to the process and ``close()`` on it is a no-op. Calling ``close()``
            unconditionally is therefore always correct.
        """
