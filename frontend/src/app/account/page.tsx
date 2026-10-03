import { AuthPage } from "@/features/account/auth-page";

export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<{ tournament?: string | string[] }>;
}) {
  const { tournament = "" } = await searchParams;
  const tournamentId = Array.isArray(tournament) ? tournament[0] ?? "" : tournament;
  return <AuthPage initialTournamentId={tournamentId} />;
}
