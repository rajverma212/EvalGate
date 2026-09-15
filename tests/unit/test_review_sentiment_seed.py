"""Tests for the review-sentiment demo narrative.

The narrative exists to show a *passing* gate, so what is asserted here is the
verdict it produces, not merely that rows were written: if the last run ever stops
clearing its baseline, the demo has silently lost its point.
"""

from __future__ import annotations

import pytest

from mrds.db import EvaluationStore, open_database
from mrds.demo.review_sentiment import (
    FEATURE_NAME,
    SPEC,
    seed_review_sentiment,
)
from mrds.regression import RegressionDetector, Severity


@pytest.fixture
def store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


def test_seeds_four_runs_and_two_baselines(store: EvaluationStore) -> None:
    result = seed_review_sentiment(store)

    assert result.seeded is True
    assert len(result.run_ids) == 4
    assert len(result.baseline_run_ids) == 2


def test_is_idempotent(store: EvaluationStore) -> None:
    seed_review_sentiment(store)
    again = seed_review_sentiment(store)

    assert again.seeded is False
    assert store.latest_run_uuid(FEATURE_NAME) is not None


def test_pass_rates_dip_then_recover(store: EvaluationStore) -> None:
    result = seed_review_sentiment(store)
    rates = [
        store.get_evaluation_result(run_id).aggregate_metrics.pass_rate for run_id in result.run_ids
    ]

    # 21, 20, 22 and 23 of 24 cases: caught, fixed, then better than it began.
    assert rates == [21 / 24, 20 / 24, 22 / 24, 23 / 24]


def test_latest_run_clears_its_baseline(store: EvaluationStore) -> None:
    """The point of the fixture: the newest run passes the gate."""
    result = seed_review_sentiment(store)
    latest = store.get_evaluation_result(result.run_ids[-1])
    baseline = store.get_active_baseline_result(FEATURE_NAME)

    assert baseline is not None
    assert latest.aggregate_metrics.pass_rate > baseline.aggregate_metrics.pass_rate

    # The gate's own verdict, not a proxy for it: comparing the newest run against the
    # active baseline must not produce a blocking result.
    comparison = RegressionDetector().compare(baseline, latest)
    assert comparison.severity is not Severity.CRITICAL
    assert not comparison.is_blocking


def test_feature_is_spec_driven_and_segmented(store: EvaluationStore) -> None:
    """It must live in the database like an onboarded feature, not in Python."""
    seed_review_sentiment(store)
    persisted = store.feature_specs.get(FEATURE_NAME)

    assert persisted is not None
    assert persisted.segment_field == "topic"
    assert SPEC.segment_field == "topic"
