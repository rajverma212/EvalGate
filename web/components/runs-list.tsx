"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, Trash2 } from "lucide-react";
import { deleteRun, type RunSummary } from "@/lib/api";
import { cn, num, pct, timeAgo } from "@/lib/utils";
import { SegmentedBar } from "@/components/ui/bar";
import { HealthDot, Tag } from "@/components/ui/status";

/** The run timeline, client-side so each row can be deleted without leaving the page. */
export function RunsList({ feature, initialRuns }: { feature: string; initialRuns: RunSummary[] }) {
  const [runs, setRuns] = useState(initialRuns);
  const [pendingUuid, setPendingUuid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const [, startTransition] = useTransition();

  async function handleDelete(run: RunSummary, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);

    if (!window.confirm(`Delete run #${run.sequence}? This can't be undone.`)) return;

    setPendingUuid(run.run_uuid);
    try {
      let result = await deleteRun(run.run_uuid);
      if (!result.deleted) {
        // Guarded (active baseline) — offer to force it, mirroring the promote-baseline UX.
        if (!window.confirm(`${result.message}\n\nDelete anyway?`)) {
          setPendingUuid(null);
          return;
        }
        result = await deleteRun(run.run_uuid, true);
      }
      if (result.deleted) {
        setRuns((prev) => prev.filter((r) => r.run_uuid !== run.run_uuid));
        startTransition(() => router.refresh()); // resync fleet/baseline state elsewhere
      } else {
        setError(result.message ?? "Could not delete this run.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this run.");
    } finally {
      setPendingUuid(null);
    }
  }

  if (runs.length === 0) {
    return (
      <div className="panel p-10 text-center">
        <p className="text-[15px] text-dim">No runs recorded for this feature yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-lg border border-critical/30 bg-critical/[0.07] px-3.5 py-2.5 text-[13px] text-critical">
          {error}
        </p>
      )}
      <div className="panel divide-y divide-line overflow-hidden">
        {runs.map((run, i) => {
          const isCritical = run.health === "critical";
          const isWarning = run.health === "warning";
          const isPending = pendingUuid === run.run_uuid;
          return (
            <Link
              key={run.run_uuid}
              href={`/features/${feature}/runs/${run.run_uuid}`}
              className={cn(
                "group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-surface-2",
                i === 0 && "rounded-t-[17px]",
                i === runs.length - 1 && "rounded-b-[17px]",
                isPending && "opacity-50",
              )}
            >
              {/* Sequence + health dot */}
              <div className="flex w-12 shrink-0 items-center gap-2">
                <HealthDot health={run.health} />
                <span className="font-mono text-[12px] text-mute">#{run.sequence}</span>
              </div>

              {/* Pass rate */}
              <div className="w-20 shrink-0 text-right">
                <span
                  className={cn(
                    "tnum text-[22px] font-semibold leading-none",
                    isCritical ? "text-critical" : isWarning ? "text-warning" : "text-bright",
                  )}
                >
                  {pct(run.pass_rate, 0)}
                </span>
              </div>

              {/* Segmented bar */}
              <div className="hidden w-28 shrink-0 sm:block">
                <SegmentedBar passed={run.passed} failed={run.failed} errored={run.errored} height={7} />
                <p className="mt-1 font-mono text-[10.5px] text-mute">
                  {run.passed}p · {run.failed}f
                  {run.errored > 0 ? ` · ${run.errored}e` : ""}
                </p>
              </div>

              {/* Tags: model, versions */}
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                <Tag>{run.model}</Tag>
                <Tag>p{run.prompt_version}</Tag>
                <Tag>d{run.dataset_version}</Tag>
                {run.is_baseline && <Tag className="border-signal/30 text-signal/90">baseline</Tag>}
              </div>

              {/* Triggered by + tokens */}
              <div className="hidden shrink-0 items-end gap-0.5 text-right md:flex md:flex-col">
                <span className="font-mono text-[11px] text-mute">{run.triggered_by}</span>
                <span className="tnum font-mono text-[11px] text-mute">{num(run.total_tokens)} tok</span>
              </div>

              {/* Time */}
              <div className="w-20 shrink-0 text-right">
                <span className="font-mono text-[12px] text-mute">{timeAgo(run.started_at)}</span>
              </div>

              {/* Delete */}
              <button
                type="button"
                onClick={(e) => handleDelete(run, e)}
                disabled={isPending}
                aria-label={`Delete run #${run.sequence}`}
                className="shrink-0 rounded-md p-1.5 text-mute opacity-0 transition-all hover:bg-critical/15 hover:text-critical group-hover:opacity-100 disabled:opacity-50"
              >
                {isPending ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
              </button>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
