# Participant bot examples

Every bot hosts three fixed HTTP endpoints on its registered LAN IP and port:

- `GET /v1/health` returns `{"protocol":"poker-bot.v1","status":"ready"}`.
- `POST /v1/verify` authenticates `Authorization: Bearer <token>` and echoes the supplied
  challenge.
- `POST /v1/action` authenticates the same token and returns one legal action before the
  request's deadline.

The JSON Schemas in `schemas/` are the public wire contract. Unknown fields, wrong protocol
versions, numeric strings, and responses with missing identifiers are rejected. `amount_to` is
only present for a raise and means the player's total commitment on the current street.

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

## JavaScript starter

The JavaScript example needs Node.js 20.9+ and no packages. See the
[main README](../../README.md) for complete Windows and macOS/Linux commands.

```shell
cd examples/bots/javascript
BOT_TOKEN=replace-with-registration-token node server.mjs
```

Register the bot machine's reachable numeric LAN IP and port `8001` in the participant
dashboard. Do not register `localhost` or `127.0.0.1`; endpoint validation rejects loopback
addresses. The configured `POKER_PARTICIPANT_SUBNET` must contain the bot's LAN address.

From the project environment, run the production conformance client against either example:

```shell
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.20 --port 8001 --token replace-with-registration-token \
  --participant-subnet 192.168.0.0/16
```

Both starters check when possible, otherwise call, otherwise fold. Edit JavaScript's
`chooseAction(state)` in `strategy.mjs`, or Python's `choose_action(state)` in `strategy.py`;
you do not need to change their server code to start building a strategy.

The dashboard also offers **Test My Bot** during open registration. It checks health,
authentication, and four synthetic decisions covering check/call, raise bounds, and short
stacks. Reports show timing and safe errors without tokens or raw responses. Any advertised
legal action passes. Tests do not verify the entrant or change tournament state; use
**Verify Bot Connection** separately before seating. Do not share a live endpoint with tests.
