# Event Deployment and Rehearsal Runbook

Use this procedure first in a full rehearsal, then again on event day. Record actual IPs, ports,
machine names, and drill results in a separate event worksheet; do not commit secrets here.

## 1. Freeze and prepare

- Check out the validated commit and retain an offline copy of the repository, Python wheels or
  environment, PostgreSQL image, and starter-bot files.
- Copy `.env.example` to `.env`. Replace the secret, set the real participant subnet and browser
  origin, and block the router, tournament host, and any infrastructure addresses.
- Confirm the application will run as one process with one Uvicorn worker.
- Start PostgreSQL, wait for its health check, then run `alembic upgrade head`.
- Create the administrator with `poker-platform bootstrap-admin --email <address>`. Supply the
  password interactively or temporarily through `POKER_ADMIN_PASSWORD`; remove it afterward.
- Start the API with `uvicorn poker_bot_platform.app:app --host 0.0.0.0 --port 8000 --workers 1`.
- Verify `GET /health` and save a fresh database backup before registration.

## 2. Prove the network

- Disable AP/client isolation and connect the tournament server by Ethernet when possible.
- Give the server a DHCP reservation. Verify every representative bot laptop can reach it.
- From the server process/container namespace, reach each bot's numeric address and port.
- Confirm participant host firewalls allow the bot port on this network profile.
- Reboot or reconnect one bot laptop, verify whether its DHCP address changes, and repeat bot
  endpoint registration if it does.
- Run the production conformance client against Python and JavaScript bots on separate laptops.
- Confirm requests to loopback, link-local, multicast, gateway, server, and off-subnet targets are
  rejected.

## 3. Dress rehearsal

- Register representative human and bot entrants, verify all bot endpoints, seat them, and start
  a seeded multi-table tournament.
- Exercise folds, calls, minimum raises, all-ins, side pots, odd chips, a table break, heads-up,
  pause/resume, a manual level advance, and tournament completion.
- During live decisions test: browser disconnect/reconnect; bot refusal; slow bot; malformed and
  oversized response; bot process death; API process death; and temporary database loss.
- For each process crash, confirm restart restores the table without duplicate accepted actions.
  A decision interrupted by restart must produce one `restart_recovery` fallback and no reissue.
- Confirm no human response or bot payload contains another entrant's hole cards or the undealt
  deck.
- Run the six-table soak on the event machine for at least eight hours. Acceptance requires zero
  chip drift, duplicate actions, stuck tables, unhandled exceptions, or unrecoverable snapshots.

## 4. Event-day checks

- Restore the frozen database or create the final tournament before opening registration.
- Keep system time synchronized. Confirm disk space, power, cooling, database health, server IP,
  AP isolation, and participant subnet before admitting entrants.
- Keep a terminal ready for application/database logs and a tested process restart. Do not edit
  poker state directly in PostgreSQL during play.
- At each break, check table progress and bot failure counts. Pause from the admin API if recovery
  is needed; the pause takes effect after current hands.
- Back up PostgreSQL after seating and after the tournament completes.

## 5. Recovery principles

- PostgreSQL unavailable: stop accepting progress, restore database service, then restart or
  restore affected coordinators. Never continue from memory alone.
- Bot unavailable or invalid: allow the normal recorded check/fold fallback; do not pause a table
  for one participant bot.
- API process unavailable: restart the exact validated build with one worker. Do not manually
  clear pending decisions.
- Router failure: administratively pause after active hands if the API remains reachable, restore
  the network, re-register changed bot addresses, then resume.
- Engine invariant failure: quarantine the affected table and preserve logs/database for review;
  do not invent a result. Other tables may continue.
