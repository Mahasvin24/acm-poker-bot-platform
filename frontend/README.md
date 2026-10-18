# ACM Poker Frontend

The production web client is a Next.js App Router application. Its root route hosts the landing
page; joining matches by code, bot management, match administration, and live play are connected
to the FastAPI backend.

## Local development

Install the locked dependencies and start the frontend from this directory:

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Useful routes are:

- `/` — public landing page
- `/join`, `/join/<code>` — enter a match code, then take a seat or seat a bot
- `/account` — account creation and sign-in; `?next=` returns to the previous page
- `/dashboard` — your matches and reusable bots (tokens, verification, diagnostics)
- `/match/<match-id>` — live lobby that becomes the table when the match starts
- `/admin`, `/admin/match/<match-id>` — create matches, share codes, manage the roster, spectate
- `/bot-guide` — bot protocol quickstart
- `/demo` — real-engine hand against three built-in bots, private to the browser
- `/play/demo` — static table preview, with no backend or login required

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
and submits only server-advertised legal actions. Player, spectator, demo, and preview tables
share `src/features/table/poker-table-view.tsx`, including timing, action labels, banners, the
finish screen, history, and showdown presentation. Pacing comes from the server
(`next_action_at`), so the table never invents delays of its own.
