import { AdminMatchConsole } from "@/features/match/admin-match-console";

export const metadata = { title: "Match management | ACM Poker" };

export default async function AdminMatchPage({ params }: { params: Promise<{ matchId: string }> }) {
  const { matchId } = await params;
  return <AdminMatchConsole matchId={matchId} />;
}
