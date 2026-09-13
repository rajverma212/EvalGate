"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Trash2 } from "lucide-react";
import { deleteFeature } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Removes a whole feature from the fleet — every run, plus its spec/prompt/dataset.
 *
 * Lives inside a card that is itself a `<Link>`, so the click must be stopped from
 * navigating. The server deliberately does not guard this (there is no baseline left to
 * protect once the feature is gone), which makes the confirmation here the only thing
 * standing between a stray click and real data loss — so it names the feature and its run
 * count rather than asking "are you sure?".
 */
export function DeleteFeatureButton({
  feature,
  displayName,
  runCount,
}: {
  feature: string;
  displayName: string;
  runCount: number;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const [, startTransition] = useTransition();

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);

    const runs = `${runCount} run${runCount === 1 ? "" : "s"}`;
    const confirmed = window.confirm(
      `Delete “${displayName}” and all ${runs}?\n\n` +
        "This removes its evaluation history, baselines, and its prompt and dataset " +
        "versions. It cannot be undone.",
    );
    if (!confirmed) return;

    setPending(true);
    try {
      await deleteFeature(feature);
      startTransition(() => router.refresh());
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not delete this feature.",
      );
      setPending(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleDelete}
        disabled={pending}
        aria-label={`Delete ${displayName}`}
        title={`Delete ${displayName}`}
        className={cn(
          "rounded-lg border border-transparent p-1.5 text-mute transition-all",
          "hover:border-critical/30 hover:bg-critical/10 hover:text-critical",
          "focus-visible:opacity-100 disabled:cursor-not-allowed disabled:opacity-50",
          // Stay out of the way until the card is hovered — but never hide from keyboards.
          "opacity-0 group-hover:opacity-100 focus:opacity-100",
        )}
      >
        {pending ? (
          <Loader2 size={15} className="animate-spin" />
        ) : (
          <Trash2 size={15} />
        )}
      </button>
      {error && (
        <span className="absolute bottom-3 right-5 text-[12px] text-critical">
          {error}
        </span>
      )}
    </>
  );
}
