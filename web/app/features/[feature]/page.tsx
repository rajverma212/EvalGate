import Link from "next/link";
import {
  ArrowRight,
  GitBranch,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  getBaseline,
  getRun,
  getRuns,
  getSummary,
  getTrend,
  type SegmentStat,
} from "@/lib/api";
import { cn, pct, points } from "@/lib/utils";
import { Reveal } from "@/components/ui/reveal";
import { ScoreRing } from "@/components/ui/gauge";
import { Meter, SegmentedBar } from "@/components/ui/bar";
import { Sparkline } from "@/components/ui/sparkline";
import { StatusPill, Tag } from "@/components/ui/status";
import { FeatureSummaryCard } from "@/components/feature-summary";

export const dynamic = "force-dynamic";

function segTone(rate: number): string {
  if (rate < 0.5) return "var(--critical)";
  if (rate < 0.85) return "var(--warning)";
  return "var(--healthy)";
}

export default async function FeatureOverview({
  params,
}: {
  params: Promise<{ feature: string }>;
}) {
  const { feature } = await params;
  const [runs, trend, baseline, summary] = await Promise.all([
    getRuns(feature),
    getTrend(feature),
    getBaseline(feature),
    getSummary(feature),
  ]);
  const latest = runs[0];
  if (!latest) {
    return (
      <div className="panel p-10 text-center text-dim">
        No runs recorded for this feature yet.
      </div>
    );
  }
  const detail = await getRun(latest.run_uuid);
  const segments = [...detail.metrics.segments].sort(
    (a, b) => a.pass_rate - b.pass_rate,
  );
  const regressed = detail.regression?.regressions ?? [];

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      {/* Left column: the verdict, then the plain-English read of it */}
      <div className="space-y-5 lg:col-span-2">
        <Reveal>
          <section className="panel p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="kicker">Latest evaluation</p>
                <p className="mt-1 text-[13px] text-mute">{latest.label}</p>
              </div>
              <StatusPill health={detail.verdict.health} />
            </div>

            <div className="mt-5 flex flex-col items-center gap-7 sm:flex-row sm:items-center">
              <ScoreRing
                value={detail.metrics.pass_rate}
                health={detail.verdict.health}
                baseline={detail.baseline?.pass_rate ?? null}
              />
              <div className="min-w-0 flex-1">
                <p className="font-display text-2xl leading-snug text-bright">
                  {detail.verdict.standing}.
                </p>
                <p className="mt-1 text-[15px] text-dim">
                  {detail.verdict.evidence}.
                </p>

                <div className="mt-4">
                  <SegmentedBar
                    passed={detail.metrics.passed}
                    failed={detail.metrics.failed}
                    errored={detail.metrics.errored}
                    height={9}
                  />
                  <div className="mt-2 flex gap-4 text-[12px] text-mute">
                    <Legend
                      color="var(--healthy)"
                      label={`${detail.metrics.passed} passed`}
                    />
                    <Legend
                      color="var(--critical)"
                      label={`${detail.metrics.failed} failed`}
                    />
                    {detail.metrics.errored > 0 && (
                      <Legend
                        color="var(--warning)"
                        label={`${detail.metrics.errored} errored`}
                      />
                    )}
                  </div>
                </div>

                <Link
                  href={`/features/${feature}/runs/${latest.run_uuid}`}
                  className="mt-5 inline-flex items-center gap-1.5 text-[13px] font-medium text-signal hover:brightness-110"
                >
                  Inspect this run <ArrowRight size={14} />
                </Link>
              </div>
            </div>

            {/* Quality breakdown */}
            <div className="mt-7 grid grid-cols-1 gap-7 border-t border-line pt-6 sm:grid-cols-2">
              <div>
                <p className="kicker mb-3">Quality by check</p>
                <div className="space-y-3.5">
                  {detail.metrics.scorers.map((s) => (
                    <Meter
                      key={s.name}
                      label={s.label}
                      value={s.mean_score}
                      color="var(--signal)"
                      trailing={pct(s.mean_score, 0)}
                    />
                  ))}
                </div>
              </div>
              <div>
                <p className="kicker mb-3">
                  Quality by {detail.segment_field ?? "segment"}
                </p>
                <div className="space-y-3.5">
                  {segments.slice(0, 6).map((s: SegmentStat) => (
                    <Meter
                      key={s.segment}
                      label={s.segment}
                      value={s.pass_rate}
                      color={segTone(s.pass_rate)}
                      trailing={`${pct(s.pass_rate, 0)}`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </section>
        </Reveal>

        {/* What all the other panels add up to, in plain English */}
        <Reveal delay={60}>
          <FeatureSummaryCard summary={summary} />
        </Reveal>
      </div>

      {/* Right column */}
      <div className="space-y-5">
        <Reveal delay={80}>
          <Link
            href={`/features/${feature}/trends`}
            className="block panel p-5 transition-colors hover:border-line-2"
          >
            <div className="flex items-center justify-between">
              <p className="kicker">Health over time</p>
              {trend.length >= 2 &&
              trend[trend.length - 1].pass_rate >= trend[0].pass_rate ? (
                <TrendingUp size={15} className="text-healthy" />
              ) : (
                <TrendingDown size={15} className="text-critical" />
              )}
            </div>
            <div className="mt-3">
              <Sparkline
                values={trend.map((t) => t.pass_rate)}
                health={detail.verdict.health}
                width={260}
                height={64}
              />
            </div>
            <p className="mt-2 text-[12.5px] text-mute">
              {trend.length} runs · {pct(trend[0]?.pass_rate, 0)} →{" "}
              {pct(trend[trend.length - 1]?.pass_rate, 0)}
            </p>
          </Link>
        </Reveal>

        <Reveal delay={140}>
          <Link
            href={`/features/${feature}/baseline`}
            className="block panel p-5 transition-colors hover:border-line-2"
          >
            <div className="flex items-center gap-2">
              <GitBranch size={15} className="text-mute" />
              <p className="kicker">Baseline</p>
            </div>
            {baseline.active ? (
              <>
                <p className="mt-3 font-mono text-2xl font-semibold text-bright tnum">
                  {pct(baseline.active.pass_rate, 0)}
                </p>
                <p className="mt-1 text-[12.5px] text-mute">
                  {baseline.active.run_label}
                </p>
              </>
            ) : (
              <p className="mt-3 text-[13px] text-dim">
                No baseline promoted yet.
              </p>
            )}
          </Link>
        </Reveal>

        {regressed.length > 0 && (
          <Reveal delay={200}>
            <Link
              href={`/features/${feature}/regressions`}
              className="block rounded-[18px] border border-critical/30 bg-critical/[0.06] p-5 transition-colors hover:bg-critical/[0.1]"
            >
              <div className="flex items-center gap-2">
                <ShieldAlert size={15} className="text-critical" />
                <p className="kicker text-critical/90">Needs attention</p>
              </div>
              <p className="mt-3 text-[14px] text-text">
                {regressed.length} metric{regressed.length > 1 ? "s" : ""}{" "}
                regressed against baseline.
              </p>
              <ul className="mt-2 space-y-1">
                {regressed.slice(0, 3).map((r) => (
                  <li
                    key={r.name}
                    className="flex items-center justify-between text-[12.5px]"
                  >
                    <span className="truncate text-dim">{r.label}</span>
                    <span className="tnum text-critical">
                      {points(r.delta)} pts
                    </span>
                  </li>
                ))}
              </ul>
              <span className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-critical">
                Root-cause analysis <ArrowRight size={13} />
              </span>
            </Link>
          </Reveal>
        )}

        <Reveal delay={260}>
          <div className="panel p-5">
            <p className="kicker mb-3">Recent runs</p>
            <div className="space-y-1">
              {runs.slice(0, 5).map((r) => (
                <Link
                  key={r.run_uuid}
                  href={`/features/${feature}/runs/${r.run_uuid}`}
                  className="flex items-center justify-between rounded-lg px-2 py-2 transition-colors hover:bg-surface-2"
                >
                  <span className="flex items-center gap-2 text-[13px] text-dim">
                    <span className="font-mono text-mute">#{r.sequence}</span>
                    {r.is_baseline && (
                      <Tag className="border-signal/30 text-signal/90">
                        baseline
                      </Tag>
                    )}
                  </span>
                  <span
                    className={cn(
                      "tnum text-[13px]",
                      r.health === "critical" ? "text-critical" : "text-text",
                    )}
                  >
                    {pct(r.pass_rate, 0)}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}
