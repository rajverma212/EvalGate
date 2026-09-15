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

// The mobile bar shares its row with the fleet chips, so the verdict is abbreviated
// there — the full sentence only has room in the desktop sidebar footer.
const gateChipLabel = (gate: string): string => {
  switch (gate) {
    case "critical":
      return "Gate blocking";
    case "warning":
      return "Gate warnings";
    case "healthy":
      return "Gate open";
    default:
      return "Gate idle";
  }
};

const gateLabel = (gate: string): string => {
  switch (gate) {
    case "critical":
      return "Blocking — critical regression";
    case "warning":
      return "Open — warnings present";
    case "healthy":
      return "Open — all green";
    default:
      return "Idle";
  }
};

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
          <NavItem href="/" icon={<Radar size={16} />} label="Home" active={onHome} />
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
            <span className="text-[13px] text-text">{gateLabel(gate)}</span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile bar. The sidebar above is `md:`-only, so without this the app has no
            navigation and never says its own name on a phone — the surface a link
            shared with someone else is most likely to be opened on. */}
        <header className="sticky top-0 z-40 border-b border-line bg-ink/80 backdrop-blur-xl md:hidden">
          <div className="flex items-center gap-3 px-4 py-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="relative grid h-6 w-6 place-items-center rounded-md bg-signal/15 ring-1 ring-signal/30">
                <span
                  className="h-1.5 w-1.5 rounded-full bg-signal animate-breathe"
                  style={{ boxShadow: "0 0 8px var(--signal)" }}
                />
              </span>
              <span className="font-display text-[17px] leading-none text-bright">
                Eval<span className="text-signal">·</span>Gate
              </span>
            </Link>
            <nav className="ml-auto flex items-center gap-1.5">
              <MobileNavItem href="/" icon={<Radar size={15} />} label="Home" active={onHome} />
              <MobileNavItem
                href="/create"
                icon={<Plus size={15} />}
                label="Create"
                active={onCreate}
              />
            </nav>
          </div>

          {/* The fleet, plus the gate verdict that is the point of the product. */}
          <div className="no-scrollbar flex items-center gap-1.5 overflow-x-auto px-4 pb-2.5">
            <span className="flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface/50 px-2.5 py-1">
              <HealthDot health={gate} />
              <span className="kicker whitespace-nowrap">{gateChipLabel(gate)}</span>
            </span>
            {fleet.map((f) => {
              const active = pathname.startsWith(`/features/${f.feature}`);
              return (
                <Link
                  key={f.feature}
                  href={`/features/${f.feature}`}
                  className={cn(
                    "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors",
                    active
                      ? "border-signal/30 bg-signal/12 text-bright"
                      : "border-line bg-surface/40 text-dim",
                  )}
                >
                  <HealthDot health={f.health} />
                  <span className="whitespace-nowrap">{f.display_name}</span>
                </Link>
              );
            })}
          </div>
        </header>

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function MobileNavItem({
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
        "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors",
        active
          ? "bg-signal/12 text-bright ring-1 ring-inset ring-signal/25"
          : "text-dim hover:bg-surface/60",
      )}
    >
      <span className={cn(active ? "text-signal" : "text-mute")}>{icon}</span>
      {label}
    </Link>
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
