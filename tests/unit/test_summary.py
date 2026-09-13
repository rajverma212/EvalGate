"""Tests for the plain-English feature summary.

The synthesis is pure, so these assert on the actual wording a user will read — that is
the product here, and vague prose is the failure mode worth guarding against.
"""

from __future__ import annotations

from mrds.dashboard.data import TrendPoint
from mrds.dashboard.summary import build_feature_summary
from mrds.evaluation.models import (
    AggregateMetrics,
    LatencyStats,
    ScorerStats,
    SegmentStats,
    TokenStats,
)
from mrds.regression.models import (
    MetricComparison,
    MetricKind,
    RegressionResult,
    Severity,
)


def _metrics(
    *,
    total: int = 20,
    passed: int = 18,
    failed: int = 2,
    errored: int = 0,
    segments: dict[str, tuple[int, int]] | None = None,
) -> AggregateMetrics:
    seg = {
        name: SegmentStats(
            segment=name, count=count, passed=ok, pass_rate=ok / count if count else 0.0
        )
        for name, (count, ok) in (segments or {}).items()
    }
    return AggregateMetrics(
        total_cases=total,
        passed=passed,
        failed=failed,
        errored=errored,
        pass_rate=passed / total if total else 0.0,
        scorers={
            "category_match": ScorerStats(
                name="category_match",
                mean_score=0.9,
                pass_rate=passed / total if total else 0.0,
                passed=passed,
                count=total,
            )
        },
        segments=seg,
        segment_field="category" if seg else None,
        latency=LatencyStats(
            count=total,
            total_ms=100.0,
            mean_ms=10.0,
            min_ms=8.0,
            p50_ms=10.0,
            p95_ms=15.0,
            max_ms=20.0,
        ),
        tokens=TokenStats(
            total_tokens=80,
            total_input_tokens=50,
            total_output_tokens=30,
            mean_tokens_per_case=8.0,
        ),
    )


def _trend(*rates: float) -> list[TrendPoint]:
    return [
        TrendPoint(
            run_uuid=f"r{i}",
            started_at="2026-01-01T00:00:00",
            pass_rate=r,
            errored=0,
            mean_latency_ms=100.0,
            p95_latency_ms=180.0,
            total_tokens=15,
            scorer_means={},
        )
        for i, r in enumerate(rates)
    ]


def _regression(*, blocking: bool, delta: float = -0.12) -> RegressionResult:
    severity = Severity.CRITICAL if blocking else Severity.WARNING
    comparison = MetricComparison(
        name="scorer.category_match.mean_score",
        kind=MetricKind.QUALITY,
        baseline_value=0.95,
        candidate_value=0.95 + delta,
        delta=delta,
        relative_delta=delta / 0.95,
        severity=severity,
        regressed=True,
        reason="dropped",
    )
    return RegressionResult(
        feature="f",
        baseline_run_id="b",
        candidate_run_id="c",
        baseline_prompt_version="v1",
        candidate_prompt_version="v1",
        baseline_dataset_version="v1",
        candidate_dataset_version="v1",
        prompt_changed=False,
        dataset_changed=False,
        severity=severity,
        comparisons=[comparison],
        regressions=[comparison],
        warning_count=0 if blocking else 1,
        critical_count=1 if blocking else 0,
    )


def _summary(**kw):
    defaults = dict(
        feature="f",
        metrics=_metrics(),
        status="healthy",
        trend=_trend(0.9, 0.9),
        baseline_pass_rate=0.9,
        comparison=None,
    )
    return build_feature_summary(**{**defaults, **kw})


def _text(summary, label: str) -> str:
    return next(p.text for p in summary.points if p.label == label)


def test_counts_are_stated_concretely_not_just_as_a_rate() -> None:
    s = _summary(metrics=_metrics(total=20, passed=18, failed=2))
    assert "18 of 20 test cases passed (90%)" in _text(s, "Latest run")
    assert "2 gave a wrong answer" in _text(s, "Latest run")


def test_a_run_below_baseline_says_so_in_points() -> None:
    s = _summary(metrics=_metrics(total=20, passed=17, failed=3), baseline_pass_rate=0.95)
    assert "10 points below the trusted baseline (85% vs 95%)" in _text(s, "Baseline")


def test_no_baseline_explains_why_nothing_can_regress() -> None:
    s = _summary(baseline_pass_rate=None)
    assert "No baseline has been promoted yet" in _text(s, "Baseline")
    assert s.gate == "No baseline yet — nothing to gate against."
    assert s.what_to_do is not None and "Promote this run as the baseline" in s.what_to_do


def test_trend_reports_direction_and_span() -> None:
    s = _summary(trend=_trend(0.95, 0.90, 0.82))
    assert "declined across the last 3 runs (95% → 82%)" in _text(s, "Trend")

    up = _summary(trend=_trend(0.70, 0.88))
    assert "improved across the last 2 runs (70% → 88%)" in _text(up, "Trend")


def test_tiny_movement_is_called_steady_not_a_trend() -> None:
    s = _summary(trend=_trend(0.90, 0.905))
    assert "held steady" in _text(s, "Trend")


def test_a_single_run_has_no_trend_line_at_all() -> None:
    s = _summary(trend=_trend(0.9))
    assert all(p.label != "Trend" for p in s.points)


def test_blocking_regression_drives_headline_gate_and_advice() -> None:
    s = _summary(status="critical", comparison=_regression(blocking=True), baseline_pass_rate=0.95)
    assert s.headline == "Quality has dropped badly enough to block a merge."
    assert s.gate == "A merge with this run would be blocked."
    assert s.what_to_do is not None and "exits non-zero" in s.what_to_do
    regressions = _text(s, "Regressions")
    assert "1 measure got worse" in regressions
    assert "1 of them badly enough to block a merge" in regressions
    # The raw metric id must never reach the reader — not even partially.
    assert "scorer." not in regressions
    assert "category_match" not in regressions
    assert "the category match check" in regressions


def test_a_clean_comparison_says_nothing_got_worse() -> None:
    clean = _regression(blocking=False).model_copy(
        update={"regressions": [], "severity": Severity.PASS, "warning_count": 0}
    )
    s = _summary(comparison=clean)
    assert _text(s, "Regressions") == "Nothing got worse compared with the baseline."
    assert s.gate == "A merge with this run would pass the gate."


def test_the_weak_segment_is_named_when_failures_concentrate() -> None:
    s = _summary(
        metrics=_metrics(
            total=20, passed=14, failed=6, segments={"billing": (10, 4), "technical": (10, 10)}
        )
    )
    weak = _text(s, "Weak spot")
    assert "billing" in weak and "40%" in weak
    assert s.what_to_do is not None and "weak spot" in s.what_to_do


def test_an_evenly_spread_failure_reports_no_weak_spot() -> None:
    s = _summary(
        metrics=_metrics(
            total=20, passed=18, failed=2, segments={"billing": (10, 9), "technical": (10, 9)}
        )
    )
    assert all(p.label != "Weak spot" for p in s.points)


def test_errors_are_distinguished_from_wrong_answers() -> None:
    s = _summary(metrics=_metrics(total=20, passed=15, failed=2, errored=3))
    errors = _text(s, "Errors")
    assert "3 cases errored out" in errors
    assert "different problem from answering wrongly" in errors
    assert s.what_to_do is not None and "Start with the errored cases" in s.what_to_do


def test_a_wholly_errored_run_is_called_out_as_not_having_executed() -> None:
    s = _summary(metrics=_metrics(total=8, passed=0, failed=0, errored=8), status="critical")
    assert s.headline == "Every case errored — this run never really executed."


def test_a_healthy_run_at_baseline_is_told_there_is_nothing_to_do() -> None:
    s = _summary(metrics=_metrics(total=20, passed=19, failed=1), baseline_pass_rate=0.9)
    assert s.headline == "Healthy, and holding at or above its baseline."
    assert s.what_to_do is not None and "good candidate to promote" in s.what_to_do


def test_a_single_critical_regression_does_not_say_all_one() -> None:
    s = _summary(status="critical", comparison=_regression(blocking=True), baseline_pass_rate=0.95)
    text = _text(s, "Regressions")
    assert "1 of them badly enough" in text
    assert "all 1" not in text, "'all 1 of them' reads worse than plain '1'"


def test_several_regressions_all_critical_say_all() -> None:
    reg = _regression(blocking=True)
    both = [reg.regressions[0], reg.regressions[0].model_copy(update={"name": "pass_rate"})]
    s = _summary(
        status="critical",
        comparison=reg.model_copy(update={"regressions": both, "critical_count": 2}),
        baseline_pass_rate=0.95,
    )
    assert "all 2 of them badly enough to block a merge" in _text(s, "Regressions")


def test_a_segment_that_fails_everything_is_described_in_words() -> None:
    s = _summary(
        metrics=_metrics(
            total=20, passed=12, failed=8, segments={"billing": (8, 0), "technical": (12, 12)}
        )
    )
    weak = _text(s, "Weak spot")
    assert "fails every one of its 8 cases" in weak
    assert "passes only 0%" not in weak
