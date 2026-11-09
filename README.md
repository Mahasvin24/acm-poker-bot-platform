# ACM Poker Bot Platform

ACM Poker is a play-money Texas Hold'em competition where ACM members build bots to compete
against other bots and human players. Your bot runs on your laptop; the platform sends it
game information over HTTP (a web request), and your code returns a legal poker action.

## Setup

### Environment

Get the competition website address and tournament invite/ID from the organizer. Participants
using that website do **not** need a local frontend, Docker, PostgreSQL, or a platform `.env`.
ACM Dev members running the full application should follow [local setup](docs/setup.md).

### Packages (prerequisites)

1. Download or clone this repository, then open a terminal in its folder.
2. Install **Node.js 20.9+**. The JavaScript starter below needs no package-install command.
   Check the installation by running `node --version` in your terminal.

Prefer Python? Use the [Python starter instructions](examples/bots/README.md#python-starter)
instead. You do not need both languages.

### Open the competition website

1. Open the organizer's website and select **Sign In / Register**. Create an account.
2. Open **Player Dashboard**, enter the tournament ID, and choose **Register as Bot**.
   Choose carefully: each account gets one human or bot entry per tournament.

### Register your bot endpoint

1. Join the competition Wi-Fi and find your laptop's IP address using the checklist below.
2. In **Bot Endpoint**, enter that address and port `8001`, then select **Save Endpoint**.
   An endpoint is the address where the platform contacts your bot.
3. Copy the one-time **bearer token**. This is a secret password the platform sends to your
   bot. Keep it private and use it below; it is not your account password.

Registration must be open. Before event day, ask for the organizer's test tournament and
network instructions.

### How to run a sample bot's API endpoint

Run the JavaScript starter from the repository folder, replacing `token-from-registration`
with your copied token. Leave the terminal open; the bot stops if you close it.

**macOS / Linux:**

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-registration' PORT=8001 node server.mjs
```

**Windows PowerShell:**

```powershell
cd examples/bots/javascript
$env:BOT_TOKEN='token-from-registration'
$env:PORT='8001'
node server.mjs
```

Open <http://localhost:8001/v1/health> on your laptop. It should show
`{"protocol":"poker-bot.v1","status":"ready"}`. This local address is only for this check.

### Networking checklist

- Connect your laptop to the network named by the organizer. Use that same network while
  registering, verifying, testing, and playing. Testing from home requires an organizer-provided
  test network/server that can reach your laptop; opening the website alone is not enough.
- Find your **LAN IP** (your laptop's address on this network):
  **Windows:** Settings → Network & internet → Wi-Fi → your connected network → IPv4 address.
  **macOS:** System Settings → Wi-Fi → Details → TCP/IP → IP address.
  **Linux:** open the connected network's settings and look under IPv4/Details.
- Save that numeric address, such as `192.168.1.42`, and port `8001` on the dashboard.
  Do not save `localhost`, `127.0.0.1`, or the competition website address.
- Allow the bot's port through your firewall when prompted. Do not disable the firewall.
  If local health works but verification fails, recheck the saved IP and network; the
  organizer's server must be able to reach your laptop. Wi-Fi changes can change your IP.

## Testing your bot

1. Select **Verify Bot Connection** on your dashboard. This checks the token and a
   verification request; it does not test poker decisions.
2. Select **Test My Bot**. Allow up to 20 seconds for six checks: health, authentication,
   check/raise, facing a bet, a short-stack call, and a short all-in raise.
3. Read each **PASS/FAIL**, response time, and error message. Fix your bot and test again.
   Any advertised legal action passes; your bot does not have to raise.
4. Check the dashboard's setup checklist. **Connection verified** is saved by verification;
   **Tests passed** describes the four decision checks from this page's last run. Neither
   a saved endpoint nor an old test report proves the bot is still running.

Passing means compatibility with these scenarios, not a winning strategy. Tests do not mark
your bot verified, change chips, or start a practice game. Test while registration is open,
before seating. If testing is busy, wait and try again.

### Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot connect | Keep the terminal open, use the competition Wi-Fi and your current LAN IP, and allow port `8001` through your firewall when prompted. |
| IP rejected | Enter a numeric LAN IP, not `localhost`, `127.0.0.1`, a hostname, or a website URL. Ask the organizer to check the allowed network if needed. |
| Authentication fails or token lost | While registration is open, use **Replace Endpoint & Token**, copy the new token, restart the bot with it, and verify again. Saving an endpoint always changes its token. |
| Invalid or late action | Follow the request's legal actions and raise bounds, echo its IDs/version, return JSON, and respond within three seconds. Check the bot terminal for errors. |
| Registration closed or endpoint in use | Test before seating; do not share an endpoint between development tests and live gameplay. |

### Change your strategy

Edit **`chooseAction(state)` in `examples/bots/javascript/strategy.mjs`**. Leave `server.mjs`
alone: it handles the connection and response format. For example, this bot checks when
checking is free and folds instead of paying to call:

```javascript
export function chooseAction(state) {
  const canCheck = state.legal_actions.some((item) => item.action === "check");
  return { action: canCheck ? "check" : "fold", amount_to: null };
}
```

Press **Ctrl+C** to stop the bot, rerun its start command, then run **Test My Bot** again.

## Joining the competition

Before seating, check that your dashboard says **Verified**, review your test report, and
leave the bot running. Keep your laptop awake on the event Wi-Fi. The organizer seats players
and starts the tournament; bot actions then happen automatically. A missed or invalid action
becomes a check when possible, otherwise a fold.

To play as a human instead, register a **Human** entry and select **Open My Table**. It waits
for the start automatically, then shows gameplay, elimination, and final results.

## Helpful references

- [Starter bots and protocol quickstart](examples/bots/README.md)
- [Request and response schemas](schemas/)
- [Full local setup for ACM Dev and organizers](docs/setup.md)
