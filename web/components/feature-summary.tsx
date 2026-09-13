import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Lightbulb,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import type { FeatureSummary, SummaryPoint } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * "So what?" — the panel that reads every other panel for you.
 *
 * Runs, trends, comparisons and regressions each show an accurate slice and each assume
 * the reader can assemble the rest. This states the conclusion in plain English, the few
 * sentences behind it, and the one thing worth doing next. All of the wording is produced
 * server-side by `dashboard/summary.py`; this component only decides how it looks.
 */
export function FeatureSummaryCard({ summary }: { summary: FeatureSummary }) {
  const blocked = summary.gate.includes("blocked");

  return (
    <section className="panel p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="kicker">What this means</p>
          <p className="mt-2 font-display text-[22px] leading-snug text-bright">
            {summary.headline}
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-medium",
            blocked
              ? "border-critical/30 bg-critical/10 text-critical"
              : "border-healthy/30 bg-healthy/10 text-healthy",
          )}
        >
          {blocked ? <ShieldX size={13} /> : <ShieldCheck size={13} />}
          {blocked ? "Merge blocked" : "Gate clear"}
        </span>
      </div>

      <ul className="mt-5 space-y-3 border-t border-line pt-5">
        {summary.points.map((point) => (
          <Point key={point.label} point={point} />
        ))}
      </ul>

      {summary.what_to_do && (
        <div className="mt-5 flex gap-3 rounded-xl border border-signal/25 bg-signal/[0.06] p-4">
          <Lightbulb size={16} className="mt-0.5 shrink-0 text-signal" />
          <div className="min-w-0">
            <p className="text-[12px] font-medium uppercase tracking-wide text-signal">
              What to do next
            </p>
            <p className="mt-1 text-[14px] leading-relaxed text-dim">
              {summary.what_to_do}
            </p>
          </div>
        </div>
      )}

      <p className="mt-4 text-[12px] text-mute">{summary.gate}</p>
    </section>
  );
}

const TONE_ICON = {
  good: CheckCircle2,
  bad: AlertTriangle,
  neutral: Info,
} as const;

const TONE_COLOR = {
  good: "text-healthy",
  bad: "text-critical",
  neutral: "text-mute",
} as const;

function Point({ point }: { point: SummaryPoint }) {
  const Icon = TONE_ICON[point.tone];
  return (
    <li className="flex gap-3">
      <Icon
        size={15}
        className={cn("mt-0.5 shrink-0", TONE_COLOR[point.tone])}
      />
      <p className="text-[14px] leading-relaxed text-dim">
        <span className="font-medium text-text">{point.label}: </span>
        {point.text}
      </p>
    </li>
  );
}
