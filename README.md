# ACM Poker Bot Platform

ACM Poker is a play-money Texas Hold'em competition where ACM members build poker bots
to compete against other bots and human players.

## Participant quickstart

Participants only need to run their bot, not the platform backend or database.

1. Open the organizer's website, create an account, and register as a bot in **Player Dashboard**.
2. Save your laptop's LAN IP and port `8001` under **Bot Endpoint**, then copy the secret token.
3. Run a starter bot below, select **Verify Bot Connection**, then **Test My Bot** before seating.
   Keep the bot running for the competition.

See the [bot guide](examples/bots/README.md) for Windows commands, networking, testing, and strategy editing.

## Setup

The following setup is for organizers and developers running the full platform locally.
Run commands from the repository root unless stated otherwise.

### Environment

Copy `.env.example` to `.env`, generate a secret with `openssl rand -hex 32`, and replace
`POKER_SECRET_KEY`. The defaults connect to the Compose PostgreSQL service and allow the local
frontend at `http://localhost:3000`.

### Packages (prerequisites)

Install Python 3.12+, Node.js 20.9+ with npm, Git, OpenSSL, and Docker with Docker Compose. Then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cd frontend
npm ci
cd ..
```

### Frontend

In a separate terminal:

```bash
cd frontend
npm run dev
```

Open <http://localhost:3000>. Use `/account` to sign in, `/admin` to run an event,
`/dashboard` to join, and `/play/demo` for the standalone table demo.

### Backend

From the repository root with the Python environment active:

```bash
docker compose up -d postgres
alembic upgrade head
poker-platform bootstrap-admin --email organizer@example.com
uvicorn poker_bot_platform.app:app --host 0.0.0.0 --port 8000 --reload
```

The API runs at <http://localhost:8000>. Use exactly one application worker; do not combine
Uvicorn's `--reload` and `--workers` options. See [local setup](docs/setup.md) for details.

### How to run a sample bot's API endpoint

After registering a bot and copying its token, run from the repository root (macOS/Linux).
The JavaScript starter needs only Node.js 20.9+ and no extra packages:

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-registration' PORT=8001 node server.mjs
```

Or, with the Python environment installed above:

```bash
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-registration' uvicorn app:app --host 0.0.0.0 --port 8001
```

Register your reachable LAN IP, not `localhost`, with port `8001` in the dashboard.
See the [bot guide](examples/bots/README.md) for participant instructions,
[architecture plan](docs/architecture-plan.md) for the design, and
[event runbook](docs/event-runbook.md) for organizers.
