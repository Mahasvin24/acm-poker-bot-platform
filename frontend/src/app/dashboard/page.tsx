import { ParticipantDashboard } from "@/features/account/participant-dashboard";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ tournament?: string }>;
}) {
  const { tournament = "" } = await searchParams;
  return <ParticipantDashboard initialTournamentId={tournament} />;
}
