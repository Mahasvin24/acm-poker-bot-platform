# Participant bot protocol (`poker-bot.v2`)

A bot is a small HTTP server you run on your own laptop on the event network. The platform
calls it whenever your seat has a decision. Every bot hosts three fixed endpoints on its
registered LAN IP and port:

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /v1/health` | none | Return `{"protocol":"poker-bot.v2","status":"ready"}`. |
| `POST /v1/verify` | bearer token | Echo the `challenge` you receive. |
| `POST /v1/action` | bearer token | Return one legal action before `deadline_at`. |

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
| `timeout` | No complete response within 3 seconds of the request (500 ms to connect). |
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
