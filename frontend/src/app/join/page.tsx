import type { Metadata } from "next";

import { JoinLanding } from "@/features/match/join-landing";

export const metadata: Metadata = {
  title: "Join a Match | ACM Poker",
  description: "Enter the match code from the organizer to take a seat or seat your bot.",
};

export default function JoinPage() {
  return <JoinLanding />;
}
