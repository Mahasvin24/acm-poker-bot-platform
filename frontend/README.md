# Poker Bot Tournament Frontend

The production web client is a Next.js App Router application. Its root route hosts the ACM
Poker Bot Tournament landing page. Account, participant, bot setup, tournament administration,
and live human gameplay flows are connected to the FastAPI backend.

## Local development

Install the locked dependencies and start the frontend from this directory:

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Useful routes are:

- `/` — public tournament landing page
- `/account` — account creation and sign-in
- `/dashboard` — participant registration, table access, and bot endpoint verification
- `/admin` — tournament creation, participant invite, settings, seating, and live controls
- `/bot-guide` — bot protocol quickstart
- `/play` — tournament ID entry
- `/play/demo` — self-contained table demo, with no backend or login required
- `/demo-human-verus-bot` — full-screen, four-player real-engine match using the shared
  production table; paced deal/street transitions protect the human decision clock, and each
  of the three built-in bots exposes a visible four-second turn
- `/play/<tournament-id>` — authenticated live table

The frontend sends `/api/v1/*` requests through the Next.js development server so browser
cookies and same-origin protections work with the FastAPI backend. It proxies to
`http://127.0.0.1:8000` by default. Copy `.env.example` to `.env.local` and set
`POKER_API_ORIGIN` if the backend uses a different origin.

See `../docs/setup.md` for complete repository setup.

## Checks

```bash
npm run lint
npm run build
```

The landing page is statically prerendered. Scroll behavior and the FAQ accordion are isolated
in `src/app/motion-controller.tsx`; the rest of the page remains server-rendered. The table
client polls the player-safe state endpoint, exposes only the signed-in player's private cards,
and submits only server-advertised legal actions. Authenticated play, `/play/demo`, and the
ephemeral match share `src/features/table/poker-table-view.tsx`, including timing, action,
animation, history, reconnection, and showdown presentation.
