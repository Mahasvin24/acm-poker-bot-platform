import { MatchRoom } from "@/features/match/match-room";

export default async function MatchPage({ params }: { params: Promise<{ matchId: string }> }) {
  const { matchId } = await params;
  return <MatchRoom matchId={matchId} />;
}
