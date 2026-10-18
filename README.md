# ACM Poker Bot Platform

A server-authoritative platform for play-money no-limit Texas Hold'em matches where humans
and student-built bots share a table.

An organizer creates a match and shares a six-character join code. Humans join in the browser;
bot builders register reusable bots once and seat them with the same code. The FastAPI backend
runs every hand through PokerKit, persists each action to PostgreSQL before advancing, paces play
so humans can follow, and resolves any bot or human failure with a recorded check or fold.

## Setup

### Environment

Copy `.env.example` to `.env`, generate a secret with `openssl rand -hex 32`, and replace
`POKER_SECRET_KEY`; the server refuses to start with the placeholder. The defaults connect to the
Compose PostgreSQL service and allow the local frontend at `http://localhost:3000`.

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

The frontend runs at <http://localhost:3000>. Players start at `/join`; organizers use `/admin`;
bot builders manage bots on `/dashboard`. `/demo` plays a hand against three built-in bots with
no account.

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

Start either example on port `8001`, add it under **My Bots** with this machine's LAN IP (not
`localhost`), paste the one-time token into `BOT_TOKEN`, restart the bot, and press **Verify**:

```bash
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-my-bots' uvicorn app:app --host 0.0.0.0 --port 8001
```

Or, with Node.js 20+ and no extra packages:

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-my-bots' PORT=8001 node server.mjs
```

See [`docs/setup.md`](docs/setup.md) for the complete local setup and checks,
[`docs/architecture-plan.md`](docs/architecture-plan.md) for the design,
[`docs/event-runbook.md`](docs/event-runbook.md) for rehearsal and deployment,
[`examples/bots/README.md`](examples/bots/README.md) for the public bot protocol, and
[`checklist.md`](checklist.md) for the platform audit.
