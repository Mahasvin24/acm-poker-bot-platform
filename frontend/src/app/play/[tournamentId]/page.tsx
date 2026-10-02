import { PokerTable } from "@/features/table/poker-table";

export default async function TournamentTablePage({
  params,
}: {
  params: Promise<{ tournamentId: string }>;
}) {
  const { tournamentId } = await params;
  return <PokerTable tournamentId={tournamentId} />;
}
