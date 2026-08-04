import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Reveal } from "@/components/ui/reveal";
import { CreateWizard } from "@/components/create-wizard";

export const dynamic = "force-dynamic";

export default function CreatePage() {
  return (
    <div className="mx-auto max-w-[1080px] px-6 py-10 md:px-10 md:py-14">
      <Reveal>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[12.5px] text-mute transition-colors hover:text-dim"
        >
          <ArrowLeft size={13} /> Mission Control
        </Link>
        <p className="kicker mt-4">Onboard a feature</p>
        <h1 className="mt-2 font-display text-4xl tracking-tight text-bright md:text-5xl">
          From dataset to evaluated feature
        </h1>
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-dim">
          Hand EvalGate a set of labeled examples. It infers the schema, picks scorers, scaffolds a
          prompt, and stands the feature up — no schema files, no scorer code.
        </p>
      </Reveal>

      <div className="mt-10">
        <Reveal delay={80}>
          <CreateWizard />
        </Reveal>
      </div>
    </div>
  );
}
