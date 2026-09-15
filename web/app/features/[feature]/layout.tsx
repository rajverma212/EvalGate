import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { getFeature } from "@/lib/api";
import { cn, pct, points } from "@/lib/utils";
import { WorkspaceNav } from "@/components/workspace-nav";
import { StatusPill, Tag } from "@/components/ui/status";
import { Button } from "@/components/ui/button";

export default async function FeatureLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ feature: string }>;
}) {
  const { feature } = await params;
  const overview = await getFeature(feature).catch(() => null);
  if (!overview) notFound();

  return (
    <div className="mx-auto max-w-[1180px] px-6 md:px-10">
      <div className="pt-9">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[12.5px] text-mute transition-colors hover:text-dim"
        >
          <ArrowLeft size={13} /> EvalGate
        </Link>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-display text-4xl leading-none tracking-tight text-bright md:text-[44px]">
                {overview.display_name}
              </h1>
              <StatusPill health={overview.health} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {overview.segment_field && <Tag>segmented by {overview.segment_field}</Tag>}
              <Tag>{overview.run_count} runs</Tag>
              <Tag className="font-mono">{feature}</Tag>
            </div>
          </div>

          <div className="flex items-end gap-6">
            <HeaderStat
              label="Latest"
              value={pct(overview.latest_pass_rate, 0)}
              sub={
                overview.baseline_delta != null
                  ? `${points(overview.baseline_delta)} pts vs baseline`
                  : "no baseline"
              }
              tone={
                overview.baseline_delta != null && overview.baseline_delta < 0 ? "down" : "flat"
              }
            />
            <HeaderStat
              label="Baseline"
              value={pct(overview.baseline_pass_rate, 0)}
              sub={overview.has_baseline ? "trusted bar" : "none set"}
            />
            {overview.latest_run_uuid && (
              <Button asChild variant="outline" size="sm" className="mb-1">
                <Link href={`/features/${feature}/runs/${overview.latest_run_uuid}`}>
                  Latest run <ArrowUpRight size={14} />
                </Link>
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-7">
        <WorkspaceNav feature={feature} />
      </div>

      <div className="py-8">{children}</div>
    </div>
  );
}

function HeaderStat({
  label,
  value,
  sub,
  tone = "flat",
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "down" | "flat";
}) {
  return (
    <div>
      <p className="kicker">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold tracking-tight text-bright tnum">{value}</p>
      <p className={cn("mt-0.5 text-[11.5px]", tone === "down" ? "text-critical" : "text-mute")}>{sub}</p>
    </div>
  );
}
