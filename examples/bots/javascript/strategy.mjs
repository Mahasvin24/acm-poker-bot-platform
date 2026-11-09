// EDIT THIS FUNCTION to change how your bot plays. Restart the bot after editing.
// Return a legal action; amount_to is only used for a raise.
export function chooseAction(state) {
  const allowed = new Set(state.legal_actions.map((item) => item.action));
  if (allowed.has("check")) return { action: "check", amount_to: null };
  if (allowed.has("call")) return { action: "call", amount_to: null };
  return { action: "fold", amount_to: null };
}
