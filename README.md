# ACM Poker Bot Platform

A server-authoritative tournament platform for a play-money human-versus-bot no-limit
Texas Hold'em club event.

The repository contains a FastAPI/PostgreSQL tournament backend and a Next.js frontend. The
current frontend includes the public tournament landing page and a human gameplay table;
registration, bot setup, and admin interfaces remain future work. 3D rendering is still
intentionally deferred.

## Development

Requirements: Python 3.12+, Node.js 20.9+, and Docker (or an existing PostgreSQL 17 instance).

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
docker compose up -d postgres
alembic upgrade head
poker-platform bootstrap-admin --email organizer@example.com
pytest
uvicorn poker_bot_platform.app:app --workers 1 --reload
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at <http://localhost:3000> and the API at <http://localhost:8000>.
The standalone table demo is available at <http://localhost:3000/play/demo>.

The service must run with exactly one application worker in v1. See
[`docs/setup.md`](docs/setup.md) for complete local setup instructions,
[`docs/architecture-plan.md`](docs/architecture-plan.md) for the frozen design,
[`docs/event-runbook.md`](docs/event-runbook.md) for rehearsal/deployment, and
[`examples/bots/README.md`](examples/bots/README.md) for the public bot protocol.

Before using the service outside local development, copy `.env.example` to `.env` and replace
the development secret.
