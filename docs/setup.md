# Local Setup

The project includes a FastAPI backend and a Next.js frontend. The frontend supports account
creation, participant and bot registration, tournament administration, and human gameplay.

## Requirements

- Python 3.12 or newer
- Node.js 20.9 or newer with npm
- Docker with Docker Compose, or an existing PostgreSQL 17 instance
- Git

Run all commands below from the repository root.

## 1. Create the Python environment

```bash
cd acm-poker-bot-platform

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Activate the virtual environment again with `source .venv/bin/activate` in each new terminal.

## 2. Configure the application

```bash
cp .env.example .env
openssl rand -hex 32
```

Open `.env` and replace `POKER_SECRET_KEY` with the generated value. The default database URL
matches the PostgreSQL service in `compose.yaml`, and the default allowed origin matches the
local Next.js frontend at `http://localhost:3000`.

For local development, the remaining defaults can normally stay unchanged. Before testing with
bot laptops, update `POKER_PARTICIPANT_SUBNET` and `POKER_BLOCKED_IPS` for the actual LAN.

## 3. Start and initialize PostgreSQL

```bash
docker compose up -d postgres
alembic upgrade head
```

To confirm PostgreSQL is healthy:

```bash
docker compose ps
```

If using an existing PostgreSQL instance instead of Compose, set `POKER_DATABASE_URL` in `.env`
before running the migration.

## 4. Create the administrator

```bash
poker-platform bootstrap-admin --email mahasvin@admin.com
```

The command prompts for a password. It creates an explicit administrator account; the email
address itself does not grant administrator access.

## 5. Start the API

```bash
uvicorn poker_bot_platform.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1
```

Version 1 must run with exactly one worker. While it is running, open:

- API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## 6. Start the frontend

In a second terminal from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Use <http://localhost:3000/play/demo> to exercise the table without
an account or running backend. For a live event:

1. Sign in as the bootstrapped administrator at <http://localhost:3000/account>.
2. Create a tournament in `/admin`, save any draft settings, and open registration.
3. Share the participant invite shown by the admin page. Each participant creates an account,
   follows the invite to `/dashboard`, and registers exactly one human or bot entry.
4. Bot entrants run a starter bot, save the one-time token shown during endpoint setup, and
   verify the endpoint before seating.
5. The administrator seats entrants and starts the tournament. Human entrants open their table
   from `/dashboard`; bot turns are dispatched automatically.

The human table reveals hole cards only to their owner, polls committed server state, and
submits decisions using the server-issued decision ID and table version.

The frontend proxies `/api/v1/*` to `http://127.0.0.1:8000` by default. If the API runs at a
different origin, create `frontend/.env.local` from `frontend/.env.example` and change
`POKER_API_ORIGIN`, then restart the frontend development server.

The committed `package-lock.json` pins the frontend dependency tree, so use `npm ci` instead of
`npm install` in CI or clean deployment environments.

## 7. Run the local checks

```bash
pytest
ruff check .
ruff format --check .
python -m mypy
cd frontend
npm run lint
npm run build
cd ..
```

The live PostgreSQL tests require a dedicated test database URL:

```bash
docker compose exec postgres createdb -U poker poker_test
POKER_TEST_DATABASE_URL='postgresql+asyncpg://poker:poker@localhost:5432/poker_test' pytest
```

The `createdb` command is needed only once. The test database name must end in `_test`; never
point these migration and isolation tests at the local application, event, or production database.

## 8. Run an example bot

After registering a bot entrant, copy the one-time token and run either starter bot in another
terminal. For the Python example:

```bash
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-registration' \
  uvicorn app:app --host 0.0.0.0 --port 8001
```

For the dependency-free JavaScript example, using Node.js 20 or newer:

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-registration' PORT=8001 node server.mjs
```

See `examples/bots/README.md` for the protocol and conformance-runner commands.

Malformed JSON, duplicate keys, schema mismatches, stale identifiers, illegal actions,
non-success HTTP responses, wrong content types, oversized responses, connection failures, and
timeouts all resolve to one deterministic automatic check-or-fold. The exact failure reason is
persisted with the action and shown in the human action log.

## Stopping the local services

Stop the API with `Ctrl-C`, then stop PostgreSQL:

```bash
docker compose down
```

The PostgreSQL data remains in the `poker-postgres` Docker volume. Running `docker compose down`
does not delete it.
