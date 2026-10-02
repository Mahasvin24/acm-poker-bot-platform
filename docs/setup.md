# Local Setup

The current milestone is a headless FastAPI service. It does not include the Next.js frontend
yet, so use the generated API documentation or direct HTTP requests to operate it locally.

## Requirements

- Python 3.12 or newer
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
matches the PostgreSQL service in `compose.yaml`. While operating the headless API through
Swagger, set `POKER_ALLOWED_ORIGIN=http://localhost:8000`. Change it back to the frontend origin
when the Next.js client is added.

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

## 6. Run the local checks

```bash
pytest
ruff check .
ruff format --check .
python -m mypy
```

The live PostgreSQL tests require a dedicated test database URL:

```bash
docker compose exec postgres createdb -U poker poker_test
POKER_TEST_DATABASE_URL='postgresql+asyncpg://poker:poker@localhost:5432/poker_test' pytest
```

The `createdb` command is needed only once. The test database name must end in `_test`; never
point these migration and isolation tests at the local application, event, or production database.

## 7. Run an example bot

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

## Stopping the local services

Stop the API with `Ctrl-C`, then stop PostgreSQL:

```bash
docker compose down
```

The PostgreSQL data remains in the `poker-postgres` Docker volume. Running `docker compose down`
does not delete it.
