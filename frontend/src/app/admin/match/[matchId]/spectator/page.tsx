import { SpectatorView } from "@/features/table/spectator-view";

export default async function SpectatorPage({ params }: { params: Promise<{ matchId: string }> }) {
  const { matchId } = await params;
  return <SpectatorView matchId={matchId} standalone />;
}
