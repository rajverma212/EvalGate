"""Seed the review-sentiment narrative: a feature that was caught, fixed, and is green.

The other two demo features end on a regression — they show the gate closing. This
one shows the other half of the story, which a fleet of only-red features cannot:
a feature that regressed, was repaired, had its improvement promoted, and now sits
above its baseline with the gate open.

The feature is **spec-driven**: it is defined by a :class:`FeatureSpec` and lives
entirely in the database, the same path a feature onboarded through the web app
takes. No new Python feature package, no core changes — which is the platform's
central claim, demonstrated rather than asserted.

Deterministic and fully offline (no Anthropic, no network, no API spend), like the
rest of :mod:`mrds.demo`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mrds.activation.discovery import (
    load_datasets_from_store,
    load_prompts_from_store,
    register_installed_features,
)
from mrds.activation.lifecycle import activate_feature_from_store
from mrds.core.registry import FeatureRegistry
from mrds.db import EvaluationStore
from mrds.demo.review_client import DeterministicReviewClient
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    ScorerKind,
    ScorerSpec,
    build_from_spec,
)
from mrds.observability.logging import get_logger
from mrds.regression import BaselineCandidate, BaselinePromoter, RegressionDetector

logger = get_logger(__name__)

FEATURE_NAME = "review_sentiment"

SPEC = FeatureSpec(
    feature_name=FEATURE_NAME,
    title="Product Review Sentiment",
    description=(
        "Triage an incoming product review: the sentiment it carries and the topic it "
        "is about, so reviews can be routed and trended without being read by hand."
    ),
    input_fields=[
        FieldSpec(name="review_text", type=FieldType.STRING, description="The review body."),
    ],
    output_fields=[
        FieldSpec(
            name="sentiment",
            type=FieldType.ENUM,
            values=["positive", "neutral", "negative"],
            description="Overall sentiment the review expresses.",
        ),
        FieldSpec(
            name="topic",
            type=FieldType.ENUM,
            values=["shipping", "quality", "price", "support"],
            description="What the review is principally about.",
        ),
    ],
    scoring=[
        ScorerSpec(field="sentiment", scorer=ScorerKind.EXACT_MATCH),
        ScorerSpec(field="topic", scorer=ScorerKind.EXACT_MATCH),
    ],
    segment_field="topic",
)

SYSTEM_PROMPT = """You triage product reviews for a consumer hardware retailer.

For each review, return two fields:

- `sentiment`: the overall feeling the reviewer expresses — `positive`, `neutral`, or
  `negative`. Judge the review as a whole. A complaint that the reviewer themselves
  dismisses ("box was dented but nothing was damaged") is not negative, and a problem
  that was resolved well is not negative either.
- `topic`: what the review is principally about — `shipping`, `quality`, `price`, or
  `support`. Choose the subject of the reviewer's judgement, not every subject they
  mention. "Built well enough to be worth the premium" is a verdict about price.

Answer with the structured fields only."""

# Each run names the cases the model gets wrong. Runs 3 and 4 are strict subsets of the
# baseline's misses, so no segment can regress and the recovery reads cleanly on every
# metric — the gate is open because the work is genuinely better, not because a
# threshold was picked to make it so.
_BASELINE_MISSES = frozenset({"rs-006", "rs-014", "rs-022"})
_REGRESSED_MISSES = _BASELINE_MISSES | {"rs-010"}
_RECOVERED_MISSES = frozenset({"rs-014", "rs-022"})
_LATEST_MISSES = frozenset({"rs-022"})


@dataclass(frozen=True)
class ReviewSeedResult:
    """Summary of the review-sentiment seeding narrative."""

    seeded: bool
    run_ids: tuple[str, ...] = ()
    baseline_run_ids: tuple[str, ...] = ()


# The golden cases ship beside the seeder rather than under ``datasets/``. That
# directory is scanned by the filesystem dataset registry, which resolves each
# feature's models through the *global* feature registry — and a spec-driven feature
# is not there until discovery has run against the database. Keeping this feature's
# data out of that directory keeps it DB-native, like any onboarded feature.
_CASES_PATH = Path(__file__).resolve().parent / "data" / "review_sentiment_cases.json"


def _load_cases() -> list[dict]:
    """Read the golden cases that get persisted into the database on activation."""
    return list(json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"])


def _client(
    cases: list[dict], miss_ids: frozenset[str], *, token_scale: float, latency_ms: float
) -> DeterministicReviewClient:
    oracle = {
        case["input"]["review_text"]: (
            case["expected_output"]["sentiment"],
            case["expected_output"]["topic"],
        )
        for case in cases
    }
    wrong_texts = frozenset(
        case["input"]["review_text"] for case in cases if case["id"] in miss_ids
    )
    return DeterministicReviewClient(
        oracle=oracle,
        wrong_texts=wrong_texts,
        token_scale=token_scale,
        latency_ms=latency_ms,
    )


def seed_review_sentiment(store: EvaluationStore) -> ReviewSeedResult:
    """Seed the four-run review-sentiment narrative if it is not already present.

    Idempotent: a persisted spec means the feature is already activated, so the
    routine no-ops rather than duplicating runs. Writes runs, one regression record,
    and two baseline promotions to the store.
    """
    if store.feature_specs.get(FEATURE_NAME) is not None:
        logger.info("Review-sentiment seed skipped: feature already activated.")
        return ReviewSeedResult(seeded=False)

    cases = _load_cases()
    detector = RegressionDetector()
    promoter = BaselinePromoter(detector)
    run_ids: list[str] = []
    baseline_run_ids: list[str] = []

    # Run 1 — activation. The same call the web app's Create flow makes, with the
    # deterministic client injected in place of Anthropic.
    first = activate_feature_from_store(
        SPEC,
        cases=cases,
        system_prompt=SYSTEM_PROMPT,
        store=store,
        client=_client(cases, _BASELINE_MISSES, token_scale=1.0, latency_ms=9.0),
        triggered_by="demo",
    )
    run_ids.append(first.run_id)
    eligibility = promoter.check(BaselineCandidate(result=first), current=None)
    if eligibility.eligible:
        store.promote_baseline(
            first.run_id, promoted_by="demo", note="Initial review-sentiment baseline"
        )
        baseline_run_ids.append(first.run_id)

    # Runs 2-4 — the dip, the fix, and the run that clears the bar it once missed.
    narrative = (
        (_REGRESSED_MISSES, 1.06, 12.0, False),
        (_RECOVERED_MISSES, 1.0, 10.0, True),
        (_LATEST_MISSES, 0.97, 9.0, False),
    )
    for miss_ids, token_scale, latency_ms, promote in narrative:
        result = _evaluate(
            store, _client(cases, miss_ids, token_scale=token_scale, latency_ms=latency_ms)
        )
        store.save_evaluation(result, triggered_by="demo")
        run_ids.append(result.run_id)

        baseline = store.get_active_baseline_result(FEATURE_NAME)
        if baseline is not None:
            store.save_regression(detector.compare(baseline, result))
        if promote:
            store.promote_baseline(
                result.run_id,
                promoted_by="demo",
                note="Promoted after the sentiment prompt was repaired",
            )
            baseline_run_ids.append(result.run_id)

    # Register it into the process's live registry. Discovery normally runs at import,
    # which is *before* this seeding, so without it the feature exists in the database
    # but not in the registry this process serves from — and anything resolving its
    # dataset models raises until the next restart.
    register_installed_features(store=store)

    logger.info(
        "Seeded review-sentiment: %d runs, %d baselines", len(run_ids), len(baseline_run_ids)
    )
    return ReviewSeedResult(
        seeded=True, run_ids=tuple(run_ids), baseline_run_ids=tuple(baseline_run_ids)
    )


def _evaluate(store: EvaluationStore, client: DeterministicReviewClient):
    """Run one evaluation for the activated feature, resolved entirely from the store."""
    prompts = load_prompts_from_store(store)
    feature = build_from_spec(SPEC, client=client, prompt_registry=prompts)
    datasets = load_datasets_from_store(
        store,
        model_resolver=lambda _f: (feature.input_model, feature.output_model),
        feature=FEATURE_NAME,
    )
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)
    return engine.run(EvaluationConfig(feature=FEATURE_NAME, segment_field=SPEC.segment_field))
