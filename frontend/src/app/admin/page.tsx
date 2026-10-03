import { AdminDashboard } from "@/features/account/admin-dashboard";

export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<{ tournament?: string }>;
}) {
  const { tournament = "" } = await searchParams;
  return <AdminDashboard initialTournamentId={tournament} />;
}
