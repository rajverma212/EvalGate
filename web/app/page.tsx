import Link from "next/link";
import { ArrowRight, ArrowUpRight, Plus, Sparkles } from "lucide-react";
import { getFeatures, type FeatureOverview } from "@/lib/api";
import { cn, pct, points } from "@/lib/utils";
import { Reveal } from "@/components/ui/reveal";
import { HealthDot, StatusPill, Tag } from "@/components/ui/status";
import { Sparkline } from "@/components/ui/sparkline";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function MissionControl() {
  const features = await getFeatures();
  const healthy = features.filter((f) => f.health === "healthy").length;
  const attention = features.filter((f) => f.health === "warning" || f.health === "critical").length;
  const rated = features.filter((f) => f.latest_pass_rate != null);
  const avg = rated.length
    ? rated.reduce((s, f) => s + (f.latest_pass_rate ?? 0), 0) / rated.length
    : null;

  return (
    <div className="mx-auto max-w-[1180px] px-6 py-10 md:px-10 md:py-14">
      {/* Hero */}
      <Reveal>
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="kicker">AI Evaluation Operating System</p>
            <h1 className="mt-3 font-display text-5xl leading-[0.95] tracking-tight text-bright md:text-6xl">
              Mission Control
            </h1>
            <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-dim">
              The health, quality, and evolution of every AI feature you ship — in one view.
              Each feature is tested against a golden dataset, compared to a trusted baseline,
              and gated before it reaches production.
            </p>
          </div>
          <Button asChild variant="signal" size="lg" className="shrink-0">
            <Link href="/create">
              <Plus size={17} /> Create a feature
            </Link>
          </Button>
        </div>
      </Reveal>

      {/* Fleet status strip */}
      <Reveal delay={80}>
        <div className="mt-10 grid grid-cols-2 divide-line rounded-2xl border border-line bg-surface/30 sm:grid-cols-4 sm:divide-x">
          <Stat label="Features tracked" value={String(features.length)} />
          <Stat label="Healthy" value={String(healthy)} tone="healthy" />
          <Stat label="Need attention" value={String(attention)} tone={attention ? "critical" : "mute"} />
          <Stat label="Fleet pass rate" value={pct(avg, 0)} mono />
        </div>
      </Reveal>

      {/* Fleet grid */}
      <div className="mt-8 flex items-center justify-between">
        <h2 className="kicker">The fleet</h2>
        <span className="kicker">Newest run · health · trend</span>
      </div>

      {features.length === 0 ? (
        <EmptyFleet />
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {features.map((f, i) => (
            <Reveal key={f.feature} delay={140 + i * 70}>
              <FeatureCard f={f} />
            </Reveal>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "mute",
  mono,
}: {
  label: string;
  value: string;
  tone?: "healthy" | "critical" | "mute";
  mono?: boolean;
}) {
  const color =
    tone === "healthy" ? "text-healthy" : tone === "critical" ? "text-critical" : "text-bright";
  return (
    <div className="px-5 py-4">
      <p className="kicker">{label}</p>
      <p className={cn("mt-1.5 text-2xl font-semibold tracking-tight", color, mono && "tnum")}>
        {value}
      </p>
    </div>
  );
}

function FeatureCard({ f }: { f: FeatureOverview }) {
  return (
    <Link
      href={`/features/${f.feature}`}
      className="group relative block overflow-hidden rounded-[18px] border border-line bg-panel p-5 transition-all duration-200 hover:-translate-y-0.5 hover:border-line-2 hover:shadow-[0_18px_50px_-24px_rgba(0,0,0,0.8)]"
    >
      {/* hover signal sheen */}
      <div className="pointer-events-none absolute -right-20 -top-20 h-48 w-48 rounded-full bg-signal/0 blur-3xl transition-all duration-300 group-hover:bg-signal/10" />

      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <HealthDot health={f.health} />
          <span className="text-[15px] font-medium text-bright">{f.display_name}</span>
        </div>
        <StatusPill health={f.health} />
      </div>

      <div className="mt-5 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-4xl font-semibold tracking-tight text-bright tnum">
              {pct(f.latest_pass_rate, 0)}
            </span>
            {f.baseline_delta != null && (
              <span
                className={cn(
                  "tnum text-sm font-medium",
                  f.baseline_delta < 0
                    ? "text-critical"
                    : f.baseline_delta > 0
                      ? "text-healthy"
                      : "text-mute",
                )}
              >
                {points(f.baseline_delta)} pts
              </span>
            )}
          </div>
          <p className="mt-1 text-[12px] text-mute">
            {f.has_baseline ? `vs baseline ${pct(f.baseline_pass_rate, 0)}` : "no baseline yet"}
          </p>
        </div>
        <div className="opacity-90">
          <Sparkline values={f.sparkline.map((p) => p.pass_rate)} health={f.health} />
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
        <div className="flex flex-wrap items-center gap-2">
          <Tag>{f.run_count} runs</Tag>
          {f.segment_field && <Tag>by {f.segment_field}</Tag>}
          {f.runs_with_regressions > 0 && (
            <Tag className="border-critical/30 text-critical/90">
              {f.runs_with_regressions} flagged
            </Tag>
          )}
        </div>
        <span className="flex items-center gap-1 text-[13px] text-mute transition-colors group-hover:text-signal">
          Open <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
        </span>
      </div>
    </Link>
  );
}

function EmptyFleet() {
  return (
    <div className="mt-4 flex flex-col items-center justify-center rounded-2xl border border-dashed border-line-2 bg-surface/20 px-6 py-20 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-xl bg-signal/12 ring-1 ring-signal/25">
        <Sparkles size={20} className="text-signal" />
      </span>
      <h3 className="mt-5 font-display text-2xl text-bright">No features under test yet</h3>
      <p className="mt-2 max-w-sm text-[14px] leading-relaxed text-dim">
        Onboard your first AI feature from a labeled dataset — EvalGate infers the schema,
        scaffolds a prompt, and runs the first evaluation.
      </p>
      <Button asChild variant="signal" className="mt-6">
        <Link href="/create">
          Create a feature <ArrowUpRight size={16} />
        </Link>
      </Button>
    </div>
  );
}
