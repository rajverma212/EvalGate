"""Plain-English synthesis of everything the platform knows about one feature.

Mission Control shows a feature across several panels — the latest run, the trend, the
comparison against baseline, the regression list, the segment breakdown. Each is accurate
and each requires the reader to already know what it means. This module answers the
question those panels leave unanswered: *so what?*

It reduces the whole picture to one headline, a handful of sentences a non-specialist can
read, and a single recommended next action. It is deliberately **pure** — every input is
passed in, nothing is fetched — so the wording is trivially testable and the module stays
feature-agnostic (it never imports a feature, and speaks only in terms of cases, metrics,
and segments).

Wording rules, applied throughout:

* Say the conclusion first, then the evidence for it.
* Prefer counts over rates where a count is more concrete ("3 of 20 cases" beats "15%"),
  and give both where the rate carries the comparison.
* Never use a metric's raw identifier. ``humanize_metric_name`` is not enough here: it
  yields ``category_match — mean score``, which still reads like a field name. This module
  has its own :func:`_readable_metric`, which says "the category match check".
* Say what it means for the user's decision, not what the number is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from mrds.dashboard.data import TrendPoint
from mrds.evaluation.models import AggregateMetrics
from mrds.regression.models import RegressionResult

#: A segment is only called out as the weak spot when it is this far below the run's own
#: overall pass rate — otherwise every run with any variation would report a "weak" segment.
_SEGMENT_GAP_THRESHOLD = 0.15

#: Below this, a segment is worth naming even if the gap is small: it is failing outright.
_SEGMENT_ABSOLUTE_FLOOR = 0.5

#: Pass-rate movement smaller than this (in rate, not points) reads as noise, not a trend.
_TREND_NOISE_FLOOR = 0.02

Tone = str  # "good" | "bad" | "neutral"


@dataclass(frozen=True)
class SummaryPoint:
    """One readable sentence about the feature, tagged for display."""

    label: str
    text: str
    tone: Tone


@dataclass(frozen=True)
class FeatureSummary:
    """The whole picture for one feature, in terms a non-specialist can act on."""

    feature: str
    headline: str
    status: str  # "healthy" | "warning" | "critical" | "unknown"
    gate: str
    points: list[SummaryPoint] = field(default_factory=list)
    what_to_do: str | None = None


def _readable_metric(name: str) -> str:
    """A flattened metric identifier as a phrase a non-specialist can read.

    Deliberately more aggressive than ``humanize_metric_name``, which is tuned for chart
    and table labels next to their own numbers. Here the name sits mid-sentence, so it has
    to survive being read aloud: ``scorer.category_match.mean_score`` becomes
    ``the category match check``, not ``category_match — mean score``.
    """
    if name == "pass_rate":
        return "the overall pass rate"
    if name == "errored":
        return "the number of cases that errored"
    if name.startswith("latency."):
        return "response speed"
    if name.startswith("tokens."):
        return "token usage"
    if name.startswith("scorer."):
        _, scorer, _metric = name.split(".", 2)
        return f"the {scorer.replace('_', ' ')} check"
    if name.startswith("segment."):
        _, segment, metric = name.split(".", 2)
        return f"the {metric.replace('_', ' ')} check in “{segment}”"
    return name.replace("_", " ")


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _points_delta(delta: float) -> str:
    """A pass-rate delta as whole percentage points, e.g. ``4 points``."""
    n = abs(round(delta * 100))
    return f"{n} point{'s' if n != 1 else ''}"


def _latest_point(metrics: AggregateMetrics) -> SummaryPoint:
    total, passed = metrics.total_cases, metrics.passed
    text = f"{passed} of {total} test cases passed ({_pct(metrics.pass_rate)})."
    if metrics.failed:
        text += f" {metrics.failed} gave a wrong answer."
    if metrics.pass_rate >= 0.9:
        tone: Tone = "good"
    elif metrics.pass_rate < 0.7:
        tone = "bad"
    else:
        tone = "neutral"
    return SummaryPoint(label="Latest run", text=text, tone=tone)


def _errors_point(metrics: AggregateMetrics) -> SummaryPoint | None:
    if not metrics.errored:
        return None
    n = metrics.errored
    return SummaryPoint(
        label="Errors",
        text=(
            f"{n} case{'s' if n != 1 else ''} errored out — the model never returned a usable "
            "answer at all. That is a different problem from answering wrongly, and usually "
            "points at the prompt, the schema, or the API rather than at quality."
        ),
        tone="bad",
    )


def _baseline_point(metrics: AggregateMetrics, baseline_pass_rate: float | None) -> SummaryPoint:
    if baseline_pass_rate is None:
        return SummaryPoint(
            label="Baseline",
            text=(
                "No baseline has been promoted yet, so there is nothing to measure this run "
                "against. Until one exists, nothing can be flagged as a regression."
            ),
            tone="neutral",
        )
    delta = metrics.pass_rate - baseline_pass_rate
    if abs(delta) < 0.005:
        return SummaryPoint(
            label="Baseline",
            text=f"Level with the baseline ({_pct(baseline_pass_rate)}).",
            tone="neutral",
        )
    direction = "above" if delta > 0 else "below"
    return SummaryPoint(
        label="Baseline",
        text=(
            f"{_points_delta(delta)} {direction} the trusted baseline "
            f"({_pct(metrics.pass_rate)} vs {_pct(baseline_pass_rate)})."
        ),
        tone="good" if delta > 0 else "bad",
    )


def _trend_point(trend: Sequence[TrendPoint]) -> SummaryPoint | None:
    if len(trend) < 2:
        return None
    first, last = trend[0].pass_rate, trend[-1].pass_rate
    delta = last - first
    span = f"across the last {len(trend)} runs ({_pct(first)} → {_pct(last)})"
    if abs(delta) < _TREND_NOISE_FLOOR:
        return SummaryPoint(
            label="Trend",
            text=f"Quality has held steady {span}.",
            tone="neutral",
        )
    verb = "improved" if delta > 0 else "declined"
    return SummaryPoint(
        label="Trend",
        text=f"Quality has {verb} {span}.",
        tone="good" if delta > 0 else "bad",
    )


def _regressions_point(comparison: RegressionResult | None) -> SummaryPoint | None:
    if comparison is None:
        return None
    if not comparison.regressions:
        return SummaryPoint(
            label="Regressions",
            text="Nothing got worse compared with the baseline.",
            tone="good",
        )
    worst = min(comparison.regressions, key=lambda m: m.delta)
    n = len(comparison.regressions)
    lead = f"{n} measure{'s' if n != 1 else ''} got worse than the baseline"
    if comparison.critical_count:
        # "5 of them" reads as a subset when it is really all of them — but "all 1"
        # is worse than plain "1", so the wording only changes when n > 1.
        count = comparison.critical_count
        which = f"all {count}" if count == n and n > 1 else str(count)
        lead += f", {which} of them badly enough to block a merge"
    detail = (
        f"The biggest drop is in {_readable_metric(worst.name)}, down {_points_delta(worst.delta)}."
    )
    return SummaryPoint(label="Regressions", text=f"{lead}. {detail}", tone="bad")


def _segment_point(metrics: AggregateMetrics) -> SummaryPoint | None:
    if len(metrics.segments) < 2:
        return None
    weakest = min(metrics.segments.values(), key=lambda s: s.pass_rate)
    gap = metrics.pass_rate - weakest.pass_rate
    if gap < _SEGMENT_GAP_THRESHOLD and weakest.pass_rate >= _SEGMENT_ABSOLUTE_FLOOR:
        return None
    field_name = metrics.segment_field or "segment"
    # "passes only 0%" is stilted; at the extremes, words beat percentages.
    if weakest.passed == 0:
        share = f"fails every one of its {weakest.count} cases"
    else:
        share = f"passes only {_pct(weakest.pass_rate)} of its {weakest.count} cases"
    return SummaryPoint(
        label="Weak spot",
        text=(
            f"Failures are concentrated in one place: {field_name} “{weakest.segment}” "
            f"{share}, against {_pct(metrics.pass_rate)} overall. Fixing that one area would "
            "move the number most."
        ),
        tone="bad",
    )


def _gate_text(comparison: RegressionResult | None, baseline_pass_rate: float | None) -> str:
    if baseline_pass_rate is None:
        return "No baseline yet — nothing to gate against."
    if comparison is None:
        return "This run is the baseline."
    if comparison.is_blocking:
        return "A merge with this run would be blocked."
    return "A merge with this run would pass the gate."


def _headline(status: str, metrics: AggregateMetrics, baseline_pass_rate: float | None) -> str:
    if metrics.errored == metrics.total_cases and metrics.total_cases:
        return "Every case errored — this run never really executed."
    if status == "critical":
        return "Quality has dropped badly enough to block a merge."
    if status == "warning":
        return "Quality slipped, but not far enough to block a merge."
    if baseline_pass_rate is None:
        return "Looking healthy — but there is no baseline yet to judge it against."
    if metrics.pass_rate >= baseline_pass_rate:
        return "Healthy, and holding at or above its baseline."
    return "Healthy overall, though slightly below its baseline."


def _what_to_do(
    status: str,
    metrics: AggregateMetrics,
    baseline_pass_rate: float | None,
    comparison: RegressionResult | None,
    segment: SummaryPoint | None,
) -> str | None:
    if comparison is not None and comparison.is_blocking:
        return (
            "Investigate before merging. CI runs the same comparison and exits non-zero, so "
            "this will block the merge until the regression is fixed or a new baseline is "
            "deliberately promoted."
        )
    if metrics.errored:
        return (
            "Start with the errored cases — they are usually a prompt or schema problem, and "
            "they drag the pass rate down without telling you anything about quality."
        )
    if segment is not None:
        return "Focus on the weak spot above; it is where the most failures are concentrated."
    if baseline_pass_rate is None:
        return (
            "Promote this run as the baseline. Nothing can be detected as a regression until "
            "there is a trusted run to compare against."
        )
    if status == "healthy" and metrics.pass_rate >= baseline_pass_rate:
        return "Nothing to do. This run is a good candidate to promote as the new baseline."
    return None


def build_feature_summary(
    *,
    feature: str,
    metrics: AggregateMetrics,
    status: str,
    trend: Sequence[TrendPoint],
    baseline_pass_rate: float | None,
    comparison: RegressionResult | None,
) -> FeatureSummary:
    """Reduce a feature's whole data picture to something a non-specialist can act on.

    Args:
        feature: The feature name (echoed back for the caller's convenience).
        metrics: Aggregate metrics of the feature's **latest** run.
        status: That run's health verdict — ``healthy``/``warning``/``critical``/``unknown``.
        trend: The feature's pass-rate time series, oldest first.
        baseline_pass_rate: The active baseline's pass rate, or ``None`` if unpromoted or
            if the latest run *is* the baseline.
        comparison: The latest run compared against the baseline, or ``None`` when there is
            no baseline to compare with (or the run is itself the baseline).

    Returns:
        A :class:`FeatureSummary`. Pure: no I/O, no database access.
    """
    segment = _segment_point(metrics)
    candidates = [
        _latest_point(metrics),
        _baseline_point(metrics, baseline_pass_rate),
        _trend_point(trend),
        _regressions_point(comparison),
        segment,
        _errors_point(metrics),
    ]
    return FeatureSummary(
        feature=feature,
        headline=_headline(status, metrics, baseline_pass_rate),
        status=status,
        gate=_gate_text(comparison, baseline_pass_rate),
        points=[p for p in candidates if p is not None],
        what_to_do=_what_to_do(status, metrics, baseline_pass_rate, comparison, segment),
    )
