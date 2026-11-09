import type { BotTestReport, Entrant } from "./types";

export function botReadiness(entrant: Entrant, verificationKnown: boolean, report: BotTestReport | null) {
  const health = report?.checks.find((check) => check.name === "Health");
  const decisions = report?.checks.filter((check) => check.name !== "Health" && check.name !== "Authentication");
  const actionTestsPassed = decisions?.length === 4 && decisions.every((check) => check.passed);
  const authentication = report?.checks.find((check) => check.name === "Authentication");
  const organizerLabels: Record<string, string> = {
    draft: "Registration has not opened",
    registration_open: "Waiting for seating — finish setup and keep your bot running",
    seated: "Seated — keep your bot running while the organizer starts play",
    running: "Tournament in progress — keep your bot running",
    pause_requested: "Tournament pausing — keep your bot running",
    paused: "Tournament paused — keep your bot running",
    break: "Tournament break — keep your bot running",
    completed: "Tournament finished",
    cancelled: "Tournament cancelled",
  };
  const organizer = verificationKnown
    ? organizerLabels[entrant.tournament_status ?? ""] ?? "Tournament status unavailable — check with the organizer"
    : "Tournament status unavailable — try again shortly";
  const connection = !verificationKnown ? "Status unavailable — try again shortly."
    : entrant.bot_verified_at
      ? authentication?.passed === false ? "Saved verification exists, but this test report's connection check failed. Check the report and rerun tests after fixing the bot." : "Verified for the saved endpoint. This does not prove decision tests passed."
      : "Not verified — select Verify Bot Connection. Test My Bot does not save verification.";
  return [
    { label: "Registered", detail: "Your bot entry is saved for this tournament." },
    { label: "Bot running", detail: health ? health.passed ? "Reached during the last test on this page. Keep its terminal open." : "Not reached during the last test. Check the bot terminal and network." : "Not checked yet — run Test My Bot." },
    { label: "Connection verified", detail: connection },
    { label: "Tests passed", detail: !report ? "Not checked on this page — run Test My Bot." : actionTestsPassed ? "All four decision checks passed in the last run. Rerun after changing your bot." : "Some decision checks failed — see the report below." },
    { label: "Waiting for organizer", detail: organizer },
  ];
}

export function botSetupError(message: string): string {
  if (message.includes("verification failed: connection")) return "Cannot reach your bot. Keep its terminal open, check the saved Wi-Fi IP address and port, and allow that port through your firewall.";
  if (message.includes("verification failed: timeout")) return "Your bot did not answer in time. Check its terminal for errors, then try Verify Bot Connection again.";
  if (message.includes("verification failed: http_status")) return "Your bot refused the request or reported an error. Restart it with the token from your saved endpoint, then check its terminal.";
  if (message.includes("bot IP must be") || message.includes("outside the participant subnet")) return "Enter your laptop's numeric Wi-Fi IP address, such as 192.168.1.42. Do not use localhost or a website URL. If the address is still rejected, ask the organizer to check the competition network.";
  return message;
}
