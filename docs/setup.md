# Local Setup

Run repository-level commands from the repository root. The platform consists of a Next.js
frontend, a single-worker FastAPI backend, PostgreSQL, and optional participant-hosted bot APIs.

## Environment

Copy the backend environment template before starting the application:

```bash
cp .env.example .env
openssl rand -hex 32
```

Replace `POKER_SECRET_KEY` in `.env` with the generated value. The default database URL matches
the PostgreSQL service in `compose.yaml`, and the default allowed origin matches the frontend at
`http://localhost:3000`.

The important backend variables are:

| Variable | Local default | Purpose |
| --- | --- | --- |
| `POKER_DATABASE_URL` | `postgresql+asyncpg://poker:poker@localhost:5432/poker` | Application database |
| `POKER_SECRET_KEY` | No safe default for real use | Session signing secret; use at least 32 characters |
| `POKER_PARTICIPANT_SUBNET` | `192.168.0.0/16` | LAN range allowed to host participant bots |
| `POKER_BLOCKED_IPS` | Router/service addresses | LAN addresses bots must not target |
| `POKER_ALLOWED_ORIGIN` | `http://localhost:3000` | Browser origin allowed by the API |
| `POKER_COOKIE_SECURE` | `false` | Set to `true` behind HTTPS |
| `POKER_WORKER_COUNT` | `1` | Version 1 requires exactly one API worker |

When the backend uses an origin other than `http://127.0.0.1:8000`, also configure the frontend:

```bash
cd frontend
cp .env.example .env.local
```

Set `POKER_API_ORIGIN` in `frontend/.env.local`, then restart the frontend development server.

> Alembic does not load the root `.env` file. If you use a non-default database, pass its URL to
> the migration command explicitly: `POKER_DATABASE_URL='postgresql+asyncpg://…' alembic upgrade
> head`. The running application and `poker-platform` CLI do load `.env`.

## Packages (prerequisites)

Install these tools before setting up the repository:

- Git
- Python 3.12 or newer
- Node.js 20.9 or newer with npm
- Docker with Docker Compose, or an existing PostgreSQL 17 instance
- OpenSSL for the secret-generation command above

Create the Python environment and install the backend with its development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Activate the environment again with `source .venv/bin/activate` in each new backend or Python-bot
terminal.

Install the locked frontend dependency tree:

```bash
cd frontend
npm ci
cd ..
```

Use `npm install` only when intentionally changing frontend dependencies. The JavaScript sample
bot has no additional package dependencies.

## Frontend

Start the frontend in its own terminal:

```bash
cd frontend
npm run dev
```

Open <http://localhost:3000>. The main routes are:

- `/account` — create an account or sign in
- `/dashboard` — join a tournament, configure a bot, or open an assigned table
- `/admin` — create and operate tournaments
- `/bot-guide` — bot protocol quickstart
- `/play/demo` — table demo that does not require an account or backend
- `/demo-human-verus-bot` — full-screen ephemeral real-engine match against three built-in bots;
  the deal and street changes pause before opening a decision, and every bot decision remains
  visible for four seconds before the server invokes it
- `/play/<tournament-id>` — authenticated live human table

The frontend proxies `/api/v1/*` to `POKER_API_ORIGIN`, which defaults to
`http://127.0.0.1:8000`.

Run the frontend checks with:

```bash
cd frontend
npm run lint
npm run build
```

## Backend

Start and initialize PostgreSQL from the repository root:

```bash
source .venv/bin/activate
docker compose up -d postgres
docker compose ps
alembic upgrade head
```

If you use an existing PostgreSQL server, export its URL when running the migration:

```bash
POKER_DATABASE_URL='postgresql+asyncpg://user:password@host:5432/database' \
  alembic upgrade head
```

Create an administrator account. The command prompts for its password:

```bash
poker-platform bootstrap-admin --email organizer@example.com
```

Start the API for local development:

```bash
uvicorn poker_bot_platform.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

For an event-like run, omit reload and declare the required single worker:

```bash
uvicorn poker_bot_platform.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1
```

Do not combine `--reload` and `--workers`. The API documentation is at
<http://localhost:8000/docs>, and the health check is at <http://localhost:8000/health>.

To run a live local tournament:

1. Sign in as the administrator at <http://localhost:3000/account>.
2. Create a tournament in `/admin`, save its settings, and open registration.
3. Share the participant invite from the admin page.
4. Each participant creates an account and registers one human or bot entry.
5. Verify all bot endpoints, seat the entrants, and start the tournament.
6. Human entrants open their assigned tables from `/dashboard`; bot turns are dispatched
   automatically.

Run the backend checks with:

```bash
pytest
ruff check .
ruff format --check .
python -m mypy
```

Live PostgreSQL tests require a dedicated database whose name ends in `_test`:

```bash
docker compose exec postgres createdb -U poker poker_test
POKER_TEST_DATABASE_URL='postgresql+asyncpg://poker:poker@localhost:5432/poker_test' pytest
```

The `createdb` command is needed only once. Never point migration or isolation tests at the local
application, event, or production database.

Stop the API with `Ctrl-C`, then stop PostgreSQL with `docker compose down`. The database remains
in the `poker-postgres` Docker volume.

## How to run a sample bot's API endpoint

First register a bot entrant from `/dashboard`. Save the one-time bearer token and enter the
machine's numeric LAN IP and port `8001`. Do not use `localhost` or `127.0.0.1`: bot endpoint
validation intentionally rejects loopback addresses. Ensure `POKER_PARTICIPANT_SUBNET` contains
the bot machine's LAN address and that the machine firewall allows the backend to reach port
`8001`.

### Python sample bot

The Python bot uses the packages installed in the project virtual environment:

```bash
source .venv/bin/activate
cd examples/bots/python
BOT_TOKEN='token-from-registration' \
  uvicorn app:app --host 0.0.0.0 --port 8001
```

### JavaScript sample bot

The JavaScript bot requires Node.js 20 or newer and has no package-install step:

```bash
cd examples/bots/javascript
BOT_TOKEN='token-from-registration' PORT=8001 node server.mjs
```

Both examples expose:

- `GET /v1/health`
- `POST /v1/verify`
- `POST /v1/action`

Confirm that the bot is listening from the bot machine:

```bash
curl http://127.0.0.1:8001/v1/health
```

The response should be `{"protocol":"poker-bot.v1","status":"ready"}`. The verification and
action endpoints require `Authorization: Bearer <token>`. Run the
conformance client against either bot by replacing the IP and token:

```bash
source .venv/bin/activate
python -m poker_bot_platform.bots.conformance \
  --ip 192.168.1.20 \
  --port 8001 \
  --token 'token-from-registration' \
  --participant-subnet 192.168.0.0/16
```

See [`../examples/bots/README.md`](../examples/bots/README.md) for the complete wire contract.
Malformed JSON, duplicate keys, schema mismatches, stale identifiers, illegal actions, wrong
content types, non-success responses, oversized responses, connection failures, and timeouts all
produce one deterministic automatic check-or-fold.
