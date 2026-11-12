import { BotDiagnosticsWindow } from "@/features/account/bot-diagnostics-window";

export const metadata = { title: "Bot diagnostics | ACM Poker" };

export default async function DiagnosticsPage({
  params,
}: {
  params: Promise<{ botId: string }>;
}) {
  const { botId } = await params;
  return <BotDiagnosticsWindow botId={botId} />;
}
