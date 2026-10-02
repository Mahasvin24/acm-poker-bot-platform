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

The Python example uses FastAPI and the platform's installed models:

```shell
cd examples/bots/python
BOT_TOKEN=replace-with-registration-token uvicorn app:app --host 0.0.0.0 --port 8001
```

The JavaScript example needs Node.js 20 or newer and no packages:

```shell
cd examples/bots/javascript
BOT_TOKEN=replace-with-registration-token node server.mjs
```

From the project environment, run the production conformance client against either example:

```shell
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.20 --port 8001 --token replace-with-registration-token \
  --participant-subnet 192.168.0.0/16
```

The reference strategy is deliberately simple and deterministic: check when possible, otherwise
call, otherwise fold. It is an integration fixture rather than a competitive bot.
