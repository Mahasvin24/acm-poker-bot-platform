import { MatchRoom } from "@/features/match/match-room";

export const metadata = { title: "Match | ACM Poker" };

export default async function MatchPage({ params }: { params: Promise<{ matchId: string }> }) {
  const { matchId } = await params;
  return <MatchRoom matchId={matchId} />;
}
