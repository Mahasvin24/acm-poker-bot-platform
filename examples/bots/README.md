# Participant bot protocol (`poker-bot.v2`)

A bot is a small HTTP server you run on your own laptop on the event network. The platform
calls it whenever your seat has a decision. The protocol has five fixed endpoints on its
registered LAN IP and port:

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /v1/health` | none | Return `{"protocol":"poker-bot.v2","status":"ready"}`. |
| `POST /v1/verify` | bearer token | Echo the `challenge` you receive. |
| `POST /v1/action` | bearer token | Return one legal action before `deadline_at`. |
| `POST /v1/game/start` | bearer token | Initialize state for a match (optional). |
| `POST /v1/game/end` | bearer token | Consume results and clear match state (optional). |

Authenticated requests carry `Authorization: Bearer <token>`. The token is shown once when you
create the bot under **My Bots**; rotating it or changing the address requires verifying again.

The JSON Schemas in [`schemas/`](../../schemas) are generated from the platform's models and
are the authoritative wire contract.

## Getting started

1. Start one of the examples below on port `8001`.
2. In the web app, open **My Bots**, add a bot with your laptop's LAN IP (for example
   `192.168.1.42`, never `localhost`) and port, then copy the token into `BOT_TOKEN` and
   restart the bot.
3. Press **Verify**. When it shows *Ready*, join a match by entering the organizer's code and
   choosing the bot.

Python (uses the platform's own models for validation):

```shell
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN=paste-token-here uvicorn app:app --host 0.0.0.0 --port 8001
```

JavaScript (Node.js 20+, no packages):

```shell
cd examples/bots/javascript
BOT_TOKEN=paste-token-here PORT=8001 node server.mjs
```

Check a bot from the repository environment before the event:

```shell
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.42 --port 8001 --token paste-token-here \
  --participant-subnet 192.168.0.0/16
```

## JavaScript starter

Install Node.js 20.9+ and check it with `node --version`. No extra packages are needed.
From the repository folder, replace `token-from-my-bots` with your copied token:

**macOS / Linux:**

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-my-bots' PORT=8001 node server.mjs
```

**Windows PowerShell:**

```powershell
cd examples/bots/javascript
$env:BOT_TOKEN='token-from-my-bots'
$env:PORT='8001'
node server.mjs
```

Leave the terminal open. Open <http://localhost:8001/v1/health> on your laptop; it should show
`{"protocol":"poker-bot.v2","status":"ready"}`. This local address is only for this check.

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
BOT_TOKEN=replace-with-my-bots-token uvicorn app:app --host 0.0.0.0 --port 8001
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
cd examples/bots/python
$env:BOT_TOKEN='replace-with-my-bots-token'
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

## Testing your bot in the browser

In **Bot configuration**, select **Test connection** to save verification of your
bot's health and token. Then expand **Decision checks and setup checklist** and
select **Test My Bot**. Allow up to 35 seconds for six checks: health, authentication,
check/raise, facing a bet, a short-stack call, and a short all-in raise.

Each check reports PASS/FAIL, response time, and an explanation. Any advertised legal
action passes; choosing a raise is optional. Tests use synthetic protocol v2 decisions,
never live game state, and do not save verification, change chips, or join a match.
The report belongs to the current page and clears when the saved endpoint changes.

Test before starting a match. Testing, endpoint edits, token rotation, and bot deletion
are blocked while the endpoint belongs to a live match, including paused matches.
An endpoint cannot be admitted into another live match while a test is running.
If testing is busy, wait and try again. Keep your bot running on the event Wi-Fi.

| Problem | What to check |
| --- | --- |
| Cannot connect | Keep the terminal open, check your saved numeric LAN IP and port, and allow the port through your firewall. |
| IP rejected | Use your laptop's address on the participant network, not localhost or a website URL. |
| Authentication fails | Show your existing token in the dashboard, copy it into BOT_TOKEN, restart, and test the connection again. |
| Invalid or late action | Choose from legal_actions, use the supplied raise bounds, echo the current identifiers, and respond within five seconds. |
| Endpoint in use | Finish the live match before changing or testing its endpoint. |

## Game lifecycle and state

A **game means the whole match**, across all of its hands. The platform attempts
`POST /v1/game/start` for every seated bot before the first action. Pause/resume does not
start a new game. A restored active match sends start again after a platform restart.

Start body:

```json
{
  "protocol": "poker-bot.v2",
  "match_id": "m-example",
  "table_id": "m-example-table",
  "entrant_id": "e-bot",
  "starting_stack": 20000,
  "blinds": { "small_blind": 100, "big_blind": 200, "big_blind_ante": 0 }
}
```

`starting_stack` and `blinds` are the match's opening configuration, including on replay.
`entrant_id` identifies your bot in action requests' public seats.

When the match completes (naturally or after an admin end request), the platform attempts
`POST /v1/game/end` for **all original bots**, including eliminated ones. Cancelling a started
match sends end with `status: "cancelled"`; cancelling a lobby sends neither hook.
Elimination alone does not send end. End body:

```json
{
  "protocol": "poker-bot.v2",
  "match_id": "m-example",
  "table_id": "m-example-table",
  "entrant_id": "e-bot",
  "status": "completed",
  "standings": [
    { "entrant_id": "e-bot", "position": 1, "final_stack": 40000 },
    { "entrant_id": "e-other", "position": 2, "final_stack": 0 }
  ]
}
```

Cancelled matches may have incomplete or empty standings; they are not final rankings.
Both hooks return HTTP 200 with `Content-Type: application/json` and the same acknowledgement:

```json
{ "protocol": "poker-bot.v2", "match_id": "m-example", "entrant_id": "e-bot" }
```

Hooks use the same bearer token, LAN restrictions, 500 ms connection timeout, 5 second total
timeout, and payload limits as actions. They are **optional, best effort notifications**:
failures are logged by the platform, do not count as action failures, and do not stop play.
There is one attempt per bot/event per platform process, without retries or durable delivery.
Existing bots returning 404 keep playing. The conformance runner reports hook results but
requires only health, verification, and action success to pass.

Key state by `match_id`, make both hooks idempotent, and lazily initialize on `/v1/action` too.
A repeated start must preserve accumulated state. A restart, network failure, or quick
cancellation can leave a bot seeing end without start, or missing end entirely. Use expiry
or bounded storage for abandoned match state; end is a cleanup opportunity, not a delivery
guarantee. These hooks do not command the platform to start or stop a match.

## A complete action request

```json
{
  "protocol": "poker-bot.v2",
  "match_id": "m-3f1c9a2b7d10",
  "table_id": "m-3f1c9a2b7d10-table",
  "hand_id": "m-3f1c9a2b7d10-table-hand-2",
  "decision_id": "6d1f0c8e-3e0b-4c8d-9a1e-2b5c7f9e1a33",
  "table_version": 3,
  "deadline_at": "2026-10-24T19:42:07.512000Z",
  "table": {
    "street": "flop",
    "button_seat": 1,
    "blinds": { "small_blind": 100, "big_blind": 200, "big_blind_ante": 0 },
    "community_cards": ["2c", "7d", "Jh"],
    "seats": [
      { "seat": 1, "entrant_id": "e-bot", "display_name": "RiverRunner", "kind": "bot",
        "stack": 19800, "committed_this_street": 0, "committed_this_hand": 200,
        "folded": false, "all_in": false, "eliminated": false },
      { "seat": 2, "entrant_id": "e-human", "display_name": "Maya", "kind": "human",
        "stack": 19800, "committed_this_street": 0, "committed_this_hand": 200,
        "folded": false, "all_in": false, "eliminated": false }
    ],
    "pot": 400,
    "side_pots": [],
    "action_history": [
      { "sequence": 1, "seat": 1, "street": "preflop", "action": "call", "amount_to": null, "automatic": false },
      { "sequence": 2, "seat": 2, "street": "preflop", "action": "check", "amount_to": null, "automatic": false }
    ]
  },
  "player": { "seat": 1, "stack": 19800, "committed_this_street": 0, "hole_cards": ["As", "Kd"] },
  "legal_actions": [
    { "action": "check", "amount": null, "min_amount_to": null, "max_amount_to": null },
    { "action": "raise", "amount": null, "min_amount_to": 200, "max_amount_to": 19800 }
  ],
  "match": {
    "hand_number": 2, "level_number": 1, "players_remaining": 2,
    "seconds_until_next_level": null, "next_small_blind": null, "next_big_blind": null
  },
  "previous_hand": {
    "hand_id": "m-3f1c9a2b7d10-table-hand-1",
    "hand_number": 1,
    "community_cards": ["Qs", "Td", "4c", "4h", "9s"],
    "shown_hands": [
      { "seat": 1, "hole_cards": ["Qh", "Jc"] },
      { "seat": 2, "hole_cards": ["8d", "8c"] }
    ],
    "awards": [{ "seat": 1, "amount": 800 }],
    "final_stacks": [
      { "seat": 1, "entrant_id": "e-bot", "stack": 20400 },
      { "seat": 2, "entrant_id": "e-human", "stack": 19600 }
    ]
  }
}
```

Field notes:

- Cards are two characters: rank `2-9TJQKA` and suit `cdhs` (`Td` is the ten of diamonds).
- All chip values are integers. `pot` includes every chip committed this hand.
- `legal_actions` always contains `check` or `fold`. A `call` carries `amount` (the extra chips
  needed); a `raise` carries `min_amount_to` and `max_amount_to`. `max_amount_to` is all-in.
- `amount_to` is a **total for the current street**, not an increment. To bet 300 on a fresh
  flop, send `amount_to: 300`; to re-raise to 900 after committing 300 this street, send
  `amount_to: 900`.
- `action_history` covers the current hand; every entry names its `street`. `automatic: true`
  means the platform acted for that seat after a timeout or bot failure.
- `previous_hand` summarizes the last completed hand at the table using public information
  only: hands shown at showdown, pot awards, and every seat's final stack. Mucked cards are never
  included. It is `null` before the first hand finishes.
- `match.seconds_until_next_level` and the `next_*_blind` fields are `null` when blinds are fixed.

## The response

```json
{
  "protocol": "poker-bot.v2",
  "match_id": "m-3f1c9a2b7d10",
  "table_id": "m-3f1c9a2b7d10-table",
  "hand_id": "m-3f1c9a2b7d10-table-hand-2",
  "decision_id": "6d1f0c8e-3e0b-4c8d-9a1e-2b5c7f9e1a33",
  "table_version": 3,
  "action": "raise",
  "amount_to": 600
}
```

Echo the five identifiers exactly. Send `amount_to` only with `raise`; omit it or send `null`
otherwise. Respond with status 200 and `Content-Type: application/json`.

## What happens when something goes wrong

Any problem resolves to exactly one automatic action (check when possible, otherwise fold) and
the hand continues. The reason is recorded and shown to you under **My Bots → Diagnostics**:

| Reason | Typical cause |
| --- | --- |
| `timeout` | No complete response within 5 seconds of the request (500 ms to connect). |
| `connection` | Wrong IP or port, bot not running, or a firewall blocking the port. |
| `http_status` | Non-2xx status; `401` usually means the token in your bot is stale. |
| `content_type` | Missing `Content-Type: application/json`. |
| `malformed_json` | Invalid JSON or a duplicated key. |
| `schema` | Wrong protocol string, misspelled or extra field, a string where an integer belongs. |
| `stale` | An echoed identifier does not match the request. |
| `illegal_action` | Action not in `legal_actions`, or a raise outside the bounds. |
| `oversized` | Response body over 4 KiB. |

After three consecutive connection, timeout, or HTTP failures, the platform calls
`/v1/health` with a 500 ms budget before each decision and skips the action request while the
bot stays unhealthy, so a crashed bot does not slow the table. One successful action resets it.

## Common mistakes

- Registering `127.0.0.1` or `localhost`. The platform runs on another machine; use your LAN IP
  and make sure your OS firewall allows the port.
- Treating `amount_to` as "chips to add". It is the street total.
- Sending `"amount_to": 0` with `check` or `call`. Only `raise` accepts a number.
- Hard-coding `"poker-bot.v1"`. The current protocol string is `poker-bot.v2`.
- Using your own clock to judge the deadline. `deadline_at` is the server's clock; aim to reply
  well within a second rather than computing remaining time.
- Restarting a bot with an old token after rotating it. Verify again after any change.
- Logging the full request including `hole_cards` to a shared screen.
