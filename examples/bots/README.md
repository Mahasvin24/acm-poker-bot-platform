# Participant bot examples

## Register your bot

You only need to run your bot, not the platform backend or database. Download or clone this
repository, then open a terminal in its folder. Choose one starter language below.

1. Get the competition website and tournament ID from the organizer. Create an account,
   open **Player Dashboard**, enter the tournament ID, and select **Register as Bot**.
   Each account gets one human or bot entry per tournament.
2. Join the competition network and find your laptop's LAN IP using the checklist below.
3. Under **Bot Endpoint**, save that numeric address and port `8001`.
4. Copy the one-time **bearer token**: a secret password the platform sends to your bot.
   Keep it private; it is not your account password. Use it in your starter's command.

Registration must be open. Before event day, ask for the organizer's test tournament and
network instructions.

## JavaScript starter

Install Node.js 20.9+ and check it with `node --version`. No extra packages are needed.
From the repository folder, replace `token-from-registration` with your copied token:

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

Leave the terminal open. Open <http://localhost:8001/v1/health> on your laptop; it should show
`{"protocol":"poker-bot.v1","status":"ready"}`. This local address is only for this check.

### Change your JavaScript strategy

Edit **`chooseAction(state)` in `examples/bots/javascript/strategy.mjs`**. Leave `server.mjs`
alone: it handles the connection and response format. For example, this checks for free and
folds instead of paying to call:

```javascript
export function chooseAction(state) {
  const canCheck = state.legal_actions.some((item) => item.action === "check");
  return { action: canCheck ? "check" : "fold", amount_to: null };
}
```

Press **Ctrl+C** to stop the bot, rerun its start command, then run **Test My Bot** again.

## Python starter


Use Python 3.12+. You only need to run your bot, not the platform's database or backend.
From the repository folder, choose the commands for your terminal and replace the token.

**macOS / Linux:**

```shell
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cd examples/bots/python
BOT_TOKEN=replace-with-registration-token uvicorn app:app --host 0.0.0.0 --port 8001
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
cd examples/bots/python
$env:BOT_TOKEN='replace-with-registration-token'
uvicorn app:app --host 0.0.0.0 --port 8001
```

Edit **`choose_action(state)` in `examples/bots/python/strategy.py`**. It returns
`(action, raise_to)`; use `None` for `raise_to` unless raising. For example, change the
function body to check for free and otherwise fold:

```python
allowed = {item.action for item in state.legal_actions}
return (ActionType.CHECK if ActionType.CHECK in allowed else ActionType.FOLD), None
```

Leave `app.py` alone: it handles authentication and response IDs. Press Ctrl+C and rerun the
last command to restart your bot after editing.

## Networking checklist

- Connect to the network named by the organizer while registering, verifying, testing, and
  playing. Testing from home requires an organizer-provided test network/server that can
  reach your laptop; opening the website alone is not enough.
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

1. Select **Verify Bot Connection**. This checks the token and a verification request;
   it does not test poker decisions.
2. Select **Test My Bot**. Allow up to 20 seconds for six checks: health, authentication,
   check/raise, facing a bet, a short-stack call, and a short all-in raise.
3. Read each **PASS/FAIL**, response time, and error message. Fix your bot and test again.
   Any advertised legal action passes; your bot does not have to raise.
4. Check the dashboard's setup checklist. **Connection verified** is saved by verification;
   **Tests passed** describes the four decision checks from this page's last run. Neither
   a saved endpoint nor an old test report proves the bot is still running.

Passing means compatibility with these scenarios, not a winning strategy. Tests do not mark
your bot verified, change chips, or start a practice game. Test while registration is open,
before seating. If testing is busy, wait and try again. Do not share an endpoint with live games.

### Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot connect | Keep the terminal open, use the competition Wi-Fi and your current LAN IP, and allow port `8001` through your firewall when prompted. |
| IP rejected | Enter a numeric LAN IP, not `localhost`, `127.0.0.1`, a hostname, or a website URL. Ask the organizer to check the allowed network if needed. |
| Authentication fails or token lost | While registration is open, use **Replace Endpoint & Token**, copy the new token, restart the bot with it, and verify again. Saving an endpoint always changes its token. |
| Invalid or late action | Follow the request's legal actions and raise bounds, echo its IDs/version, return JSON, and respond within three seconds. Check the bot terminal for errors. |
| Registration closed or endpoint in use | Test before seating; do not share an endpoint between development tests and live gameplay. |

## Joining the competition

Before seating, check that your dashboard says **Verified**, review your test report, and
leave the bot running. Keep your laptop awake on the event Wi-Fi. The organizer seats players
and starts the tournament; bot actions happen automatically. A missed or invalid action
becomes a check when possible, otherwise a fold.

To play as a human instead, register a **Human** entry and select **Open My Table**.

## Protocol reference

Every bot hosts three fixed HTTP endpoints on its registered LAN IP and port:

- `GET /v1/health` returns `{"protocol":"poker-bot.v1","status":"ready"}`.
- `POST /v1/verify` authenticates `Authorization: Bearer <token>` and echoes the supplied
  challenge.
- `POST /v1/action` authenticates the same token and returns one legal action before the
  request's deadline.

The [JSON Schemas](../../schemas/) are the public wire contract. Unknown fields, wrong protocol
versions, numeric strings, and responses with missing identifiers are rejected. `amount_to` is
the player's total commitment on the current street for a raise; use `null` or omit it otherwise.

## Optional CLI check

From the project environment, run the production conformance client against either example:

```shell
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.20 --port 8001 --token replace-with-registration-token \
  --participant-subnet 192.168.0.0/16
```

Both starters check when possible, otherwise call, otherwise fold. Return to the
[project README](../../README.md) for full-platform setup links.
