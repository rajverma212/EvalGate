"""Tests for the libSQL / Turso storage backend and its sqlite3-compatibility adapter.

Runs the full store/repository stack — and DB-native activation — over a local libSQL
file, proving a second engine works behind :class:`StorageBackend` with no change above
the persistence layer. Skipped if the optional ``libsql`` package is not installed.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

pytest.importorskip("libsql")

from mrds.activation.lifecycle import activate_feature_from_store  # noqa: E402
from mrds.config.settings import Settings  # noqa: E402
from mrds.dashboard.data import DashboardData  # noqa: E402
from mrds.db import DbError, EvaluationStore, LibsqlBackend, create_backend  # noqa: E402
from mrds.db.backends.libsql import _Row  # noqa: E402
from mrds.llm.base import LLMMessage, LLMResult  # noqa: E402
from mrds.onboarding import infer_feature_spec  # noqa: E402

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app crashes"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "reset my password"},
            "expected_output": {"category": "account"},
        },
        {
            "id": "c4",
            "input": {"text": "send me an invoice"},
            "expected_output": {"category": "billing"},
        },
    ]
}
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _RAW["cases"]}


class _Stub:
    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        label = _ORACLE.get(messages[-1].content, "billing")
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
        )


# -- the row adapter ------------------------------------------------------------


def test_row_supports_index_name_and_dict() -> None:
    row = _Row(["feature_name", "version"], ["email_classifier", "v1"])
    assert row[0] == "email_classifier"  # positional (PRAGMA/COUNT paths)
    assert row["version"] == "v1"  # by-name (repositories)
    assert dict(row) == {"feature_name": "email_classifier", "version": "v1"}  # model_validate path
    assert list(row) == ["email_classifier", "v1"]


# -- backend selection ----------------------------------------------------------


def test_factory_builds_libsql_backend_from_settings() -> None:
    backend = create_backend(Settings(storage_backend="libsql", database_path="ignored.db"))
    assert isinstance(backend, LibsqlBackend)
    assert backend.name == "libsql"


def test_factory_rejects_unknown_backend() -> None:
    # Settings' Literal already rejects bad names at construction; this covers the
    # factory's own defensive guard via a stand-in settings object.
    class _Settings:
        storage_backend = "nope"
        database_path = "x.db"
        libsql_sync_url = None
        libsql_auth_token = None

    with pytest.raises(DbError, match="unknown storage backend"):
        create_backend(_Settings())  # type: ignore[arg-type]


# -- full stack over libSQL -----------------------------------------------------


def test_libsql_backend_runs_activation_end_to_end(tmp_path) -> None:
    backend = LibsqlBackend(tmp_path / "eval.db")
    store = EvaluationStore(backend.connect())

    spec = infer_feature_spec(_RAW, feature_name="lib_feat", feature_type="classification")
    result = activate_feature_from_store(
        spec,
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )

    assert result.aggregate_metrics.total_cases == 4
    # The full bundle + run persisted and read back through the libSQL connection.
    data = DashboardData(store)
    assert "lib_feat" in data.features()
    assert [r.run_uuid for r in data.runs("lib_feat")] == [result.run_id]
    view = data.dataset_view("lib_feat")
    assert view is not None and view.case_count == 4

    # Baseline promotion (a write path through the transaction wrapper) works too.
    store.promote_baseline(result.run_id, promoted_by="test", note="first")
    assert data.active_baseline("lib_feat") is not None


def test_libsql_persists_across_reconnects(tmp_path) -> None:
    """Durability parity: a new connection to the same file sees prior writes."""
    db_file = tmp_path / "eval.db"
    store = EvaluationStore(LibsqlBackend(db_file).connect())
    spec = infer_feature_spec(_RAW, feature_name="persist_me", feature_type="classification")
    activate_feature_from_store(
        spec, cases=_RAW["cases"], system_prompt="Classify. JSON.", store=store, client=_Stub()
    )

    reopened = EvaluationStore(LibsqlBackend(db_file).connect())
    assert "persist_me" in DashboardData(reopened).features()


# -- sync throttling (the perceived-lag fix) -------------------------------------


def test_replica_sync_is_throttled_not_per_connect(tmp_path, monkeypatch) -> None:
    """Regression test for the ~1s-per-request lag: an unconditional ``.sync()`` on every
    connect turned every API request into a network round-trip. Only the first connect
    within the throttle window should sync; later ones (same sync_url) reuse the local
    file with no network call, until the window elapses.

    A real local libSQL connection provides genuine query/bootstrap behavior; only
    ``.sync()`` is faked (counted, no network) so this test needs no live Turso creds.
    """
    import time

    import libsql

    import mrds.db.backends.libsql as libsql_backend

    sync_calls = {"count": 0}
    real_connect = libsql.connect

    class _CountingSyncProxy:
        """Delegates everything to a real local connection except ``.sync()`` (counted,
        no network) — the real connection type is a Rust extension object and its
        attributes can't be monkeypatched directly."""

        def __init__(self, real: object) -> None:
            self._real = real

        def sync(self) -> None:
            sync_calls["count"] += 1

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

    def fake_connect(path: str, **kwargs: object) -> object:
        # sync_url/auth_token are accepted (matching the real signature) but ignored —
        # delegate to a genuine local connection so schema/bootstrap behavior is real.
        return _CountingSyncProxy(real_connect(path))

    monkeypatch.setattr(libsql, "connect", fake_connect)
    libsql_backend._last_synced_at.clear()  # isolate from other tests/processes

    backend = libsql_backend.LibsqlBackend(
        tmp_path / "t.db", sync_url="fake://primary", auth_token="tok"
    )

    backend.connect().close()
    assert sync_calls["count"] == 1  # first connect in the window: syncs

    backend.connect().close()
    backend.connect().close()
    assert sync_calls["count"] == 1  # same window: no additional network sync

    # Simulate the throttle window having elapsed.
    libsql_backend._last_synced_at["fake://primary"] = (
        time.monotonic() - libsql_backend._SYNC_INTERVAL_SECONDS - 1
    )
    backend.connect().close()
    assert sync_calls["count"] == 2  # window elapsed: syncs again


# -- shared warm connections (the per-request connect-cost fix) -------------------


@pytest.fixture(autouse=True)
def _no_leaked_shared_connections() -> Iterator[None]:
    """Shared connections are process-scoped by design; keep them from crossing tests."""
    from mrds.db.backends.libsql import reset_shared_connections

    reset_shared_connections()
    yield
    reset_shared_connections()


def test_shared_connect_reuses_one_connection_private_connect_does_not(tmp_path) -> None:
    """The fix itself: read callers reuse one warm connection instead of each paying to
    open one. Against Turso that handshake is a ~150-750 ms network round-trip per call."""
    backend = LibsqlBackend(tmp_path / "eval.db")

    first = backend.connect(shared=True)
    second = backend.connect(shared=True)
    assert first is second, "shared readers must reuse the process's warm connection"
    assert first.is_shared

    # A second backend instance pointed at the same database shares it too — each request
    # builds its own backend object, so the cache cannot live on the instance.
    assert LibsqlBackend(tmp_path / "eval.db").connect(shared=True) is first

    private = backend.connect()
    assert private is not first, "writers must get their own connection"
    assert not private.is_shared
    private.close()


def test_shared_connections_are_keyed_by_database(tmp_path) -> None:
    a = LibsqlBackend(tmp_path / "a.db").connect(shared=True)
    b = LibsqlBackend(tmp_path / "b.db").connect(shared=True)
    assert a is not b


def test_closing_a_shared_session_leaves_the_connection_usable(tmp_path) -> None:
    """Every request closes its session; a shared connection must survive that, since
    other in-flight requests are still using it."""
    backend = LibsqlBackend(tmp_path / "eval.db")
    db = backend.connect(shared=True)

    db.close()  # what ApiSession.close() does — a no-op for a shared connection

    # Still usable by the next caller.
    assert DashboardData(EvaluationStore(backend.connect(shared=True))).features() == []


def test_reset_closes_shared_connections_for_real(tmp_path) -> None:
    from mrds.db.backends.libsql import reset_shared_connections

    backend = LibsqlBackend(tmp_path / "eval.db")
    first = backend.connect(shared=True)
    reset_shared_connections()
    assert backend.connect(shared=True) is not first, "reset must force a fresh connection"


def test_shared_connection_serves_concurrent_readers(tmp_path) -> None:
    """Sharing is only safe because the driver enforces no thread affinity and serialises
    concurrent use internally — FastAPI runs sync endpoints on a threadpool."""
    import threading

    backend = LibsqlBackend(tmp_path / "eval.db")
    seed_db = backend.connect()
    spec = infer_feature_spec(_RAW, feature_name="shared_feat", feature_type="classification")
    activate_feature_from_store(
        spec,
        cases=_RAW["cases"],
        system_prompt="Classify. JSON.",
        store=EvaluationStore(seed_db),
        client=_Stub(),
    )
    seed_db.close()

    errors: list[str] = []
    seen: list[list[str]] = []

    def reader() -> None:
        try:
            for _ in range(25):
                data = DashboardData(EvaluationStore(backend.connect(shared=True)))
                seen.append(data.features())
        except Exception as exc:  # noqa: BLE001 - any failure is the finding
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert seen == [["shared_feat"]] * 200


def test_shared_replica_delegates_freshness_to_the_driver(tmp_path, monkeypatch) -> None:
    """A shared connection is long-lived, so it must ask the driver to refresh the replica
    on a background timer rather than have a request pay for an explicit (~290 ms) sync."""
    import libsql

    import mrds.db.backends.libsql as libsql_backend

    calls: list[dict[str, object]] = []
    sync_calls = {"count": 0}
    real_connect = libsql.connect

    class _CountingSyncProxy:
        def __init__(self, real: object) -> None:
            self._real = real

        def sync(self) -> None:
            sync_calls["count"] += 1

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

    def fake_connect(path: str, **kwargs: object) -> object:
        calls.append(kwargs)
        return _CountingSyncProxy(real_connect(path))

    monkeypatch.setattr(libsql, "connect", fake_connect)
    libsql_backend._last_synced_at.clear()

    backend = libsql_backend.LibsqlBackend(
        tmp_path / "t.db", sync_url="fake://primary", auth_token="tok"
    )
    backend.connect(shared=True)
    backend.connect(shared=True)
    backend.connect(shared=True)

    assert len(calls) == 1, "the replica handshake is paid once, not once per caller"
    assert calls[0]["sync_interval"] == libsql_backend._SYNC_INTERVAL_SECONDS
    assert sync_calls["count"] == 0, "no request should block on an explicit sync"


def test_local_libsql_file_gets_no_sync_interval(tmp_path, monkeypatch) -> None:
    """``sync_interval`` is meaningless without a primary to sync from; don't send it."""
    import libsql

    import mrds.db.backends.libsql as libsql_backend

    calls: list[dict[str, object]] = []
    real_connect = libsql.connect

    def fake_connect(path: str, **kwargs: object) -> object:
        calls.append(kwargs)
        return real_connect(path)

    monkeypatch.setattr(libsql, "connect", fake_connect)
    libsql_backend.LibsqlBackend(tmp_path / "t.db").connect(shared=True)
    assert calls == [{}]


def test_dead_shared_connection_is_replaced_not_reused(tmp_path) -> None:
    """A shared connection outlives the request that opened it, so it can be found dead
    later (a serverless instance frozen and thawed, a dropped replica session). One bad
    handle must not poison every later request for the life of the process."""
    backend = LibsqlBackend(tmp_path / "eval.db")
    first = backend.connect(shared=True)

    first.close(force=True)  # simulate the handle dying underneath us
    assert not first.is_usable()

    replacement = backend.connect(shared=True)
    assert replacement is not first, "a dead shared connection must be reopened"
    assert replacement.is_usable()
    assert DashboardData(EvaluationStore(replacement)).features() == []

    # ...and the replacement is then itself cached, not reopened per call.
    assert backend.connect(shared=True) is replacement


def test_live_shared_connection_is_not_needlessly_reopened(tmp_path) -> None:
    """The liveness probe must not cost a reconnect on the happy path — that would undo
    the entire point of sharing."""
    import libsql

    import mrds.db.backends.libsql as libsql_backend

    connects = {"count": 0}
    real_connect = libsql.connect

    def counting_connect(path: str, **kwargs: object) -> object:
        connects["count"] += 1
        return real_connect(path, **kwargs)

    backend = libsql_backend.LibsqlBackend(tmp_path / "eval.db")
    backend.connect(shared=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(libsql, "connect", counting_connect)
        for _ in range(10):
            backend.connect(shared=True)
    assert connects["count"] == 0
