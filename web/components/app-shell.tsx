"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, Plus, Radar } from "lucide-react";
import { cn } from "@/lib/utils";
import { HealthDot } from "@/components/ui/status";

interface FleetItem {
  feature: string;
  display_name: string;
  health: string;
}

const worstHealth = (items: FleetItem[]): string => {
  if (items.some((i) => i.health === "critical")) return "critical";
  if (items.some((i) => i.health === "warning")) return "warning";
  if (items.length && items.every((i) => i.health === "healthy")) return "healthy";
  return "unknown";
};

export function AppShell({ fleet, children }: { fleet: FleetItem[]; children: React.ReactNode }) {
  const pathname = usePathname();
  const onHome = pathname === "/";
  const onCreate = pathname.startsWith("/create");
  const gate = worstHealth(fleet);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-line bg-ink/60 px-4 pb-5 pt-6 backdrop-blur-xl md:flex">
        {/* Wordmark */}
        <Link href="/" className="group mb-8 flex items-center gap-2.5 px-2">
          <span className="relative grid h-7 w-7 place-items-center rounded-md bg-signal/15 ring-1 ring-signal/30">
            <span className="h-2 w-2 rounded-full bg-signal animate-breathe" style={{ boxShadow: "0 0 8px var(--signal)" }} />
          </span>
          <span className="font-display text-[19px] leading-none text-bright">
            Eval<span className="text-signal">·</span>Gate
          </span>
        </Link>

        <nav className="space-y-1">
          <NavItem href="/" icon={<Radar size={16} />} label="Mission Control" active={onHome} />
          <NavItem href="/create" icon={<Plus size={16} />} label="Create feature" active={onCreate} />
        </nav>

        <div className="mb-2 mt-7 flex items-center justify-between px-2">
          <span className="kicker">Fleet</span>
          <span className="kicker tnum">{fleet.length}</span>
        </div>
        <div className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
          {fleet.map((f) => {
            const active = pathname.startsWith(`/features/${f.feature}`);
            return (
              <Link
                key={f.feature}
                href={`/features/${f.feature}`}
                className={cn(
                  "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  active ? "bg-surface-2 text-bright" : "text-dim hover:bg-surface/60 hover:text-text",
                )}
              >
                <HealthDot health={f.health} />
                <span className="truncate">{f.display_name}</span>
                {active && <span className="ml-auto h-3.5 w-0.5 rounded-full bg-signal" />}
              </Link>
            );
          })}
          {fleet.length === 0 && (
            <p className="px-3 py-2 text-[13px] leading-relaxed text-mute">
              No features evaluated yet.
            </p>
          )}
        </div>

        {/* Gate status footer */}
        <div className="mt-4 rounded-xl border border-line bg-surface/40 p-3">
          <div className="flex items-center gap-2">
            <Boxes size={14} className="text-mute" />
            <span className="kicker">Deploy gate</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <HealthDot health={gate} />
            <span className="text-[13px] text-text">
              {gate === "critical"
                ? "Blocking — critical regression"
                : gate === "warning"
                  ? "Open — warnings present"
                  : gate === "healthy"
                    ? "Open — all green"
                    : "Idle"}
            </span>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

function NavItem({
  href,
  icon,
  label,
  active,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-signal/12 text-bright ring-1 ring-inset ring-signal/25"
          : "text-dim hover:bg-surface/60 hover:text-text",
      )}
    >
      <span className={cn(active ? "text-signal" : "text-mute")}>{icon}</span>
      {label}
    </Link>
  );
}
