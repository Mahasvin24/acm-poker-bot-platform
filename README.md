# ACM Poker Bot Platform

A server-authoritative, headless tournament platform for a play-money human-versus-bot
no-limit Texas Hold'em club event.

The first milestone deliberately contains no frontend. It proves poker rules, durable state,
bot isolation, restart recovery, and six-table tournament orchestration before a minimal
Next.js client is considered.

## Development

Requirements: Python 3.12+ and Docker (or an existing PostgreSQL 17 instance).

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

The service must run with exactly one application worker in v1. See
[`docs/architecture-plan.md`](docs/architecture-plan.md) for the frozen design,
[`docs/event-runbook.md`](docs/event-runbook.md) for rehearsal/deployment, and
[`examples/bots/README.md`](examples/bots/README.md) for the public bot protocol.

Before using the service outside local development, copy `.env.example` to `.env` and replace
the development secret. The headless milestone intentionally has no Next.js or 3D client.
