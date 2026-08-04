import type { Metadata } from "next";
import { Hanken_Grotesk, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { getFeatures } from "@/lib/api";

const display = Instrument_Serif({
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-instrument",
});

const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-hanken",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "EvalGate — AI Evaluation Operating System",
  description:
    "The control plane for the health, quality, and evolution of your AI features. Evaluate against golden datasets, catch regressions, and gate deploys.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const features = await getFeatures();
  const fleet = features.map((f) => ({
    feature: f.feature,
    display_name: f.display_name,
    health: f.health,
  }));

  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} ${mono.variable} antialiased`}
    >
      <body>
        <AppShell fleet={fleet}>{children}</AppShell>
      </body>
    </html>
  );
}
