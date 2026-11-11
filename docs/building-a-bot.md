# Building a Poker Bot

This guide explains how to build and connect a participant-hosted bot to the ACM Poker Bot
Platform. A bot can be written in any language that can run an HTTP server and read and write
JSON. The platform is the client: it sends requests to the bot running on your laptop whenever
the bot has a decision to make.

The current protocol is `poker-bot.v2`. For runnable starting points, see the
[Python example](../examples/bots/python/app.py) and the
[JavaScript example](../examples/bots/javascript/server.mjs). The files in [`schemas/`](../schemas)
are the authoritative JSON Schemas, and [`examples/bots/README.md`](../examples/bots/README.md)
is the full wire-protocol reference.

## 1. Implement the bot endpoints

Your server must listen on a port from `1024` through `65535` and expose these exact paths:

| Method and path | Authentication | Purpose |
| --- | --- | --- |
| `GET /v1/health` | None | Tell the platform that the bot is ready. |
| `POST /v1/verify` | Bearer token | Prove that the platform has reached the correct bot. |
| `POST /v1/action` | Bearer token | Choose one legal action for the current decision. |
| `POST /v1/game/start` | Bearer token | Optional: initialize match state. |
| `POST /v1/game/end` | Bearer token | Optional: read final results and release match state. |

Every successful response must be JSON and include a `Content-Type: application/json` header.
Do not redirect these routes.

### Health

Return this response from `GET /v1/health`:

```json
{
  "protocol": "poker-bot.v2",
  "status": "ready"
}
```

The health endpoint is intentionally unauthenticated. Keep it free of secrets and private state.

### Verification

The platform sends a request like this to `POST /v1/verify`:

```http
Authorization: Bearer your-one-time-token
Content-Type: application/json
```

```json
{
  "protocol": "poker-bot.v2",
  "challenge": "a-random-challenge-generated-by-the-platform"
}
```

First validate the bearer token, then return the challenge unchanged:

```json
{
  "protocol": "poker-bot.v2",
  "challenge": "a-random-challenge-generated-by-the-platform"
}
```

Read the expected token from an environment variable such as `BOT_TOKEN`; do not commit it to
source control or print it in logs.

### Action

`POST /v1/action` receives the bot's private cards, the public table state, the legal actions, and
identifiers for the current decision. The complete request shape is shown in the
[protocol reference](../examples/bots/README.md#a-complete-action-request).

The response must echo these five values exactly as they appeared in the request:

- `match_id`
- `table_id`
- `hand_id`
- `decision_id`
- `table_version`

A check response, for example, is:

```json
{
  "protocol": "poker-bot.v2",
  "match_id": "m-3f1c9a2b7d10",
  "table_id": "m-3f1c9a2b7d10-table",
  "hand_id": "m-3f1c9a2b7d10-table-hand-2",
  "decision_id": "6d1f0c8e-3e0b-4c8d-9a1e-2b5c7f9e1a33",
  "table_version": 3,
  "action": "check",
  "amount_to": null
}
```

Choose only an action present in `legal_actions`:

| Action | Response `amount_to` |
| --- | --- |
| `fold` | Omit it or send `null`. |
| `check` | Omit it or send `null`. |
| `call` | Omit it or send `null`; the request's `amount` tells you the call cost. |
| `raise` | Send an integer from `min_amount_to` through `max_amount_to`, inclusive. |

For a raise, `amount_to` is the total number of chips the bot will have committed on the current
street, not the number of additional chips to add. If the bot has already committed 300 and wants
to raise to 900, return `"amount_to": 900`.

## 2. Start with a safe strategy

Get the networking and protocol correct before writing poker logic. A useful first strategy is:

1. Check if `check` is legal.
2. Otherwise call if `call` is legal.
3. Otherwise fold.

In pseudocode:

```text
allowed = the action names in request.legal_actions

if "check" is in allowed:
    action = "check"
else if "call" is in allowed:
    action = "call"
else:
    action = "fold"

return the action plus the five identifiers copied from the request
```

This deliberately simple bot is enough to validate the complete integration. Once it works,
replace only the action-selection function. Useful inputs include:

- `player.hole_cards` and `table.community_cards`
- each seat's stack and commitments
- `table.pot` and `table.side_pots`
- `table.action_history`, including the street for every action
- call cost and legal raise bounds in `legal_actions`
- blind level and remaining-player information in `match`
- public showdown information from `previous_hand`

Cards use two characters: rank `2-9TJQKA`, followed by suit `cdhs`. For example, `As` is the ace
of spades and `Td` is the ten of diamonds. Chip amounts are always integers.

Do not assume that every optional context value is present. `match` may be `null`,
`previous_hand` is `null` before a hand has completed, and blind-timer fields are `null` in a
fixed-blind match. Never expect another player's unshown hole cards.

## 3. Run the bot on the event network

Bind the server to `0.0.0.0`, not only to `127.0.0.1`, so the platform machine can reach it. Find
your laptop's numeric LAN address (often similar to `192.168.1.42`) and allow the bot's port through
your operating-system firewall.

Do not register `localhost`, `127.0.0.1`, a hostname, or a public internet address. Bot addresses
must be numeric addresses inside the event's configured participant subnet.

You can run either included starter from the repository root:

```bash
# Python 3.12+; uses the repository's installed development environment
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-my-bots' uvicorn app:app --host 0.0.0.0 --port 8001
```

```bash
# Node.js 20+; no package installation is required
cd examples/bots/javascript
BOT_TOKEN='token-from-my-bots' PORT=8001 node server.mjs
```

Confirm locally that the process is listening:

```bash
curl http://127.0.0.1:8001/v1/health
```

Then test from another machine on the same network using the laptop's LAN IP. A local health
check can succeed even when the firewall or network prevents the platform machine from connecting.

## 4. Register, verify, and join

1. Sign in to the platform and open **My Bots** on the dashboard.
2. Add the bot's name, numeric LAN IP, and listening port.
3. Copy the bearer token immediately; it is shown only when created or rotated.
4. Set `BOT_TOKEN` to that value and restart the bot process.
5. Select **Verify Connection**. The bot is ready when the dashboard shows it as verified.
6. Enter a match's join code and choose the verified bot as the entrant.

The bot profile can be reused for later matches. If its IP address or port changes, update the
profile and verify it again. If the token is rotated, replace the old environment value, restart
the bot, and verify again.

## 5. Test protocol conformance

With the bot running on its LAN address, run the repository's black-box conformance client:

```bash
source .venv/bin/activate
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.42 \
  --port 8001 \
  --token 'token-from-my-bots' \
  --participant-subnet 192.168.0.0/16
```

Replace the IP, token, and subnet with the event's values. A passing report has `true` for
`health`, `verified`, and `action_accepted`.

Before the event, also test these cases:

- a decision where checking is legal;
- a decision where the bot must call or fold;
- minimum and maximum legal raises;
- all-in and side-pot states;
- a restarted bot with the correct token; and
- reachability from the actual platform machine, not only from the bot laptop.

## Timing and strictness

The platform allows 500 ms to establish a connection and no more than 5 seconds for an entire bot
request. Aim to answer comfortably within one second. `deadline_at` uses the platform server's
clock, so do not use the bot laptop's clock to calculate how much time remains.

Responses are parsed strictly:

- the response body must be no larger than 4 KiB;
- duplicate JSON keys and extra fields are rejected;
- numeric strings and booleans do not count as integers;
- a non-2xx response or wrong content type is a failure;
- stale identifiers, an unlisted action, or an out-of-range raise is rejected; and
- redirects are not followed.

On any failure or timeout, the platform records the reason and automatically checks when possible,
otherwise folds, so the match can continue. Recent results are visible under
**My Bots → Diagnostics**.

## Common problems

| Symptom | Likely cause and fix |
| --- | --- |
| Health works locally but verification fails | Use the LAN IP, bind to `0.0.0.0`, open the firewall, and test from the platform machine. |
| Verification returns `401` | The bot is using an old or mistyped token. Replace `BOT_TOKEN` and restart it. |
| Failure reason is `content_type` | Set the response header to `Content-Type: application/json`. |
| Failure reason is `schema` | Check the protocol version, types, required fields, and extra fields against [`schemas/`](../schemas). |
| Failure reason is `stale` | Copy all five decision identifiers from the current request without caching or regenerating them. |
| Failure reason is `illegal_action` | Choose from `legal_actions`; for a raise, use its inclusive bounds and treat `amount_to` as the street total. |
| Failure reason is `timeout` | Remove slow network calls or expensive computation from the decision path. |
| Bot worked before its address changed | Update the profile in **My Bots** and verify the connection again. |

Keep request logging private: action requests contain your bot's hole cards. Never log the bearer
token, and avoid showing full payloads on a shared screen during a match.

## Match state lifecycle

For stateful bots, implement `POST /v1/game/start` and `POST /v1/game/end`.
A game is the whole match, not an individual hand. Start is attempted before play; end is
attempted on completion or cancellation, including for eliminated bots. Pause/resume keeps
the same state. Both respond with `protocol`, `match_id`, and `entrant_id` echoed as JSON.

Key state by `match_id`. Preserve it on duplicate starts, initialize it on action requests
when absent, and remove it on end. Notifications are optional and best effort, with a
5 second deadline and no retries. Start can repeat after a platform restart; either hook
can be missed. Expire abandoned state. Failed hooks do not prevent actions or fail readiness.
See [the lifecycle payloads and delivery details](../examples/bots/README.md#game-lifecycle-and-state).
