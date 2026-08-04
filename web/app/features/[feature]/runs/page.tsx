import { getRuns } from "@/lib/api";
import { Reveal } from "@/components/ui/reveal";
import { RunsList } from "@/components/runs-list";

export const dynamic = "force-dynamic";

export default async function RunsTimeline({
  params,
}: {
  params: Promise<{ feature: string }>;
}) {
  const { feature } = await params;
  const runs = await getRuns(feature);

  if (runs.length === 0) {
    return (
      <Reveal>
        <div className="panel p-10 text-center">
          <p className="text-[15px] text-dim">No runs recorded for this feature yet.</p>
          <p className="mt-1.5 text-[13px] text-mute">
            Trigger an evaluation via the CLI to see runs here.
          </p>
        </div>
      </Reveal>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <Reveal>
        <div className="flex items-baseline justify-between">
          <div>
            <p className="kicker">Run history</p>
            <p className="mt-1 text-[13px] text-mute">{runs.length} total · newest first</p>
          </div>
        </div>
      </Reveal>

      {/* Timeline */}
      <Reveal delay={70}>
        <RunsList feature={feature} initialRuns={runs} />
      </Reveal>
    </div>
  );
}
