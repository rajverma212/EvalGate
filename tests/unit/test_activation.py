"""Tests for feature activation: discovering and registering DB-persisted specs."""

from __future__ import annotations

from collections.abc import Sequence

from mrds.activation import register_installed_features
from mrds.activation.lifecycle import activate_feature_from_store
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.db import EvaluationStore, open_database
from mrds.features.spec import compute_spec_hash
from mrds.llm.base import LLMMessage, LLMResult
from mrds.onboarding import infer_feature_spec

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app crashes on launch"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "reset my password please"},
            "expected_output": {"category": "account"},
        },
    ]
}


def _persist_spec(store: EvaluationStore, name: str) -> None:
    """Persist a feature spec into the store, as DB-native activation does."""
    spec = infer_feature_spec(_RAW, feature_name=name, feature_type="classification")
    store.feature_specs.upsert(
        feature_name=name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )


def test_store_discovery_registers_persisted_spec() -> None:
    store = EvaluationStore(open_database(":memory:"))
    _persist_spec(store, "from_db")

    registry = FeatureRegistry()
    names = register_installed_features(store=store, registry=registry)
    assert names == ["from_db"]
    assert "from_db" in registry

    # Idempotent: a second pass registers nothing new.
    assert register_installed_features(store=store, registry=registry) == []


def test_discovery_noop_when_no_specs(tmp_path) -> None:
    store = EvaluationStore(open_database(":memory:"))
    registry = FeatureRegistry()
    # No specs on disk and none in the store -> nothing registered.
    assert (
        register_installed_features(specs_dir=tmp_path / "nope", store=store, registry=registry)
        == []
    )
    assert len(registry) == 0


def test_global_registry_only_has_handwritten_features() -> None:
    # No specs/ dir in the repo and no store passed at import -> the global discovery hook
    # registers only the hand-coded built-ins.
    assert feature_registry.names() == ["email_classifier", "ticket_router"]


class _Stub:
    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        label = {
            "please refund my charge": "billing",
            "the app crashes on launch": "technical",
            "reset my password please": "account",
        }.get(messages[-1].content, "billing")
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
        )


def test_rediscovered_db_only_feature_evaluates_in_a_fresh_process() -> None:
    """Regression test: a feature activated purely through the web (no filesystem
    bundle) must still be runnable from a *second*, independent evaluation — e.g. a
    later `mrds evaluate` in a fresh process/registry, exactly what `bootstrap_platform`
    does. Before the fix, `register_installed_features` built the feature with no
    prompt registry, so it silently fell back to filesystem discovery, found nothing
    (this feature was never written to disk), and every case errored.
    """
    from mrds.activation.discovery import load_datasets_from_store, load_prompts_from_store
    from mrds.evaluation import EvaluationConfig, EvaluationEngine

    store = EvaluationStore(open_database(":memory:"))
    spec = infer_feature_spec(_RAW, feature_name="rediscover_me", feature_type="classification")
    activate_feature_from_store(
        spec,
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )

    # Simulate a brand-new process: a fresh registry, rediscovering purely from the DB —
    # exactly what CliRuntime.build_runtime()/bootstrap_platform does for a later run.
    fresh_registry = FeatureRegistry()
    assert register_installed_features(store=store, registry=fresh_registry) == ["rediscover_me"]

    # register_installed_features deliberately builds features with no injected LLM
    # client (production registration always uses the real configured client). Swap in
    # a stub so this test needs no API key — orthogonal to the prompt-registry fix
    # being verified here.
    fresh_registry.get("rediscover_me")._client = _Stub()  # noqa: SLF001

    def _resolver(feature: str) -> tuple[type, type]:
        instance = fresh_registry.get(feature)
        return instance.input_model, instance.output_model

    engine = EvaluationEngine(
        features=fresh_registry,
        prompts=load_prompts_from_store(store),
        datasets=load_datasets_from_store(store, feature="rediscover_me", model_resolver=_resolver),
    )
    result = engine.run(EvaluationConfig(feature="rediscover_me"))

    assert result.aggregate_metrics.errored == 0
    assert result.aggregate_metrics.total_cases == 3
    assert result.aggregate_metrics.pass_rate == 1.0
