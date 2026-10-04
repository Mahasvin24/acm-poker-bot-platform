# ACM Poker Bot Platform

A server-authoritative tournament platform for a play-money human-versus-bot no-limit
Texas Hold'em club event.

The repository contains a FastAPI/PostgreSQL tournament backend and a Next.js frontend. The
web experience covers account creation, tournament administration, participant registration,
bot endpoint setup and verification, and a server-authoritative human gameplay table. 3D
rendering remains intentionally deferred.

## Setup

### Environment

Copy `.env.example` to `.env`, generate a secret with `openssl rand -hex 32`, and replace
`POKER_SECRET_KEY`. The defaults connect to the Compose PostgreSQL service and allow the local
frontend at `http://localhost:3000`.

### Packages (prerequisites)

Install Python 3.12+, Node.js 20.9+ with npm, Git, and Docker with Docker Compose. Then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cd frontend
npm ci
cd ..
```

### Frontend

```bash
cd frontend
npm run dev
```

The frontend runs at <http://localhost:3000>. Use `/account` to sign in, `/admin` to run an
event, `/dashboard` to join one as a human or bot, `/play/demo` for the standalone table, and
`/demo-human-verus-bot` for an ephemeral four-player real-engine match with three deliberately
paced test bots.

### Backend

From the repository root with the Python environment active:

```bash
docker compose up -d postgres
alembic upgrade head
poker-platform bootstrap-admin --email organizer@example.com
uvicorn poker_bot_platform.app:app --host 0.0.0.0 --port 8000 --reload
```

The API runs at <http://localhost:8000>. Version 1 uses exactly one application worker; do not
combine Uvicorn's `--reload` and `--workers` options.

### How to run a sample bot's API endpoint

After registering a bot and copying its one-time token, start either example on port `8001`:

```bash
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-registration' uvicorn app:app --host 0.0.0.0 --port 8001
```

Or, with Node.js 20+ and no extra packages:

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-registration' PORT=8001 node server.mjs
```

Register the machine's reachable LAN IP—not `localhost`—with port `8001` in the participant
dashboard.

See [`docs/setup.md`](docs/setup.md) for the complete local setup and checks,
[`docs/architecture-plan.md`](docs/architecture-plan.md) for the frozen design,
[`docs/event-runbook.md`](docs/event-runbook.md) for rehearsal/deployment, and
[`examples/bots/README.md`](examples/bots/README.md) for the public bot protocol.
