import { cn } from "@/lib/utils";

const LABELS: Record<string, string> = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
  unknown: "No data",
  pass: "Pass",
};

const TONE: Record<string, { fg: string; bg: string; ring: string }> = {
  healthy: { fg: "text-healthy", bg: "bg-healthy/10", ring: "ring-healthy/25" },
  pass: { fg: "text-healthy", bg: "bg-healthy/10", ring: "ring-healthy/25" },
  warning: { fg: "text-warning", bg: "bg-warning/10", ring: "ring-warning/25" },
  critical: { fg: "text-critical", bg: "bg-critical/12", ring: "ring-critical/30" },
  unknown: { fg: "text-mute", bg: "bg-white/5", ring: "ring-white/10" },
};

/** A small pulsing dot keyed by health — the platform's core "signal" element. */
export function HealthDot({ health, className }: { health: string; className?: string }) {
  const tone = TONE[health] ?? TONE.unknown;
  return (
    <span className={cn("relative inline-flex h-2 w-2", className)}>
      {(health === "critical" || health === "warning") && (
        <span
          className={cn("absolute inline-flex h-full w-full rounded-full opacity-60 animate-ping", tone.bg)}
          style={{ backgroundColor: "currentColor" }}
        />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", tone.fg)} style={{ backgroundColor: "currentColor" }} />
    </span>
  );
}

/** A verdict pill: dot + label, ring-bordered, tinted by health. */
export function StatusPill({
  health,
  label,
  className,
}: {
  health: string;
  label?: string;
  className?: string;
}) {
  const tone = TONE[health] ?? TONE.unknown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        tone.bg,
        tone.fg,
        tone.ring,
        className,
      )}
    >
      <HealthDot health={health} />
      {label ?? LABELS[health] ?? health}
    </span>
  );
}

export function Tag({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  /** Hover text, for a tag whose meaning is not self-evident. */
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-line bg-surface/50 px-2 py-0.5 font-mono text-[11px] text-dim",
        className,
      )}
    >
      {children}
    </span>
  );
}
