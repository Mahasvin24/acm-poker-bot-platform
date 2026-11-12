import { JoinMatch } from "@/features/match/join-match";

export const metadata = { title: "Join a match | ACM Poker" };

export default async function JoinCodePage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <JoinMatch code={code} />;
}
