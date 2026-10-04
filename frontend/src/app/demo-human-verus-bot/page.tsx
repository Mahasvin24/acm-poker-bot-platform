import type { Metadata } from "next";

import { DemoMatch } from "../../features/demo-match/demo-match";

export const metadata: Metadata = {
  title: "Human versus Bots Demo | ACM Poker",
  description: "Run an ephemeral four-player poker match against three built-in test bots.",
};

export default function DemoHumanVersusBotPage() {
  return <DemoMatch />;
}
