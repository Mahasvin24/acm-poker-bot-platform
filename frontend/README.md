# Poker Bot Tournament Frontend

The production web client is a Next.js App Router application. Its root route hosts the ACM
Poker Bot Tournament landing page, and `/play/[tournamentId]` provides the human table interface.
Registration, bot setup, and admin routes will be added as separate application flows after
their contracts are connected.

## Local development

From this directory:

```bash
npm install
npm run dev
```

Open <http://localhost:3000>. Useful routes are:

- `/` — public tournament landing page
- `/play` — tournament ID entry
- `/play/demo` — self-contained table demo, with no backend or login required
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
client polls the player-safe state endpoint and submits only server-advertised legal actions.
