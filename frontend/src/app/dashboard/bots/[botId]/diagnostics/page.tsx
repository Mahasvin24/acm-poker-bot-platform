import { BotDiagnosticsWindow } from "@/features/account/bot-diagnostics-window";

export default async function DiagnosticsPage({
  params,
}: {
  params: Promise<{ botId: string }>;
}) {
  const { botId } = await params;
  return <BotDiagnosticsWindow botId={botId} />;
}
