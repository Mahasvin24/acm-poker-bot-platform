import { AdminMatchConsole } from "@/features/match/admin-match-console";

export default async function AdminMatchPage({ params }: { params: Promise<{ matchId: string }> }) {
  const { matchId } = await params;
  return <AdminMatchConsole matchId={matchId} />;
}
