# ACM Poker Bot Platform

A server-authoritative, headless tournament platform for a play-money human-versus-bot
no-limit Texas Hold'em club event.

The first milestone deliberately contains no frontend. It proves poker rules, durable state,
bot isolation, restart recovery, and six-table tournament orchestration before a minimal
Next.js client is considered.

## Development

Requirements: Python 3.12+ and Docker.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
docker compose up -d postgres
pytest
uvicorn poker_bot_platform.app:app --workers 1 --reload
```

The service must run with exactly one application worker in v1. See
[`docs/architecture-plan.md`](docs/architecture-plan.md) for the design and event assumptions.

