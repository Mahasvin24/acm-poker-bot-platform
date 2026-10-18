import { JoinMatch } from "@/features/match/join-match";

export default async function JoinCodePage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <JoinMatch code={code} />;
}
