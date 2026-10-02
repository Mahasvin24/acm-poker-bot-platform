# Poker Bot Tournament Frontend

The production web client is a Next.js App Router application. Its root route currently hosts
the ACM Poker Bot Tournament landing page. Registration, participant play, bot setup, and admin
routes will be added as separate application flows after their contracts are connected.

## Local development

From this directory:

```bash
npm install
npm run dev
```

Open <http://localhost:3000>. The FastAPI backend runs separately on
<http://localhost:8000>; see `../docs/setup.md` for complete repository setup.

## Checks

```bash
npm run lint
npm run build
```

The landing page is statically prerendered. Scroll behavior and the FAQ accordion are isolated
in `src/app/motion-controller.tsx`; the rest of the page remains server-rendered.
