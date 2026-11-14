# whatsonyourmind · Mindy

> Just text Mindy on WhatsApp: save anything, find it in plain words, get reminders in any time zone.
> Then the free Mindy app for friends, plans and games.

**Status:** pre-launch, everything built. The marketing website (Lovable, this repo's `src/`) and the
**Mindy server** (`server/`: the real Mindy app, WhatsApp, Instagram and Telegram bots, family care, khata, scam
shield, screenshot help) are ready to deploy. See **[server/DEPLOY.md](server/DEPLOY.md)** and **[docs/VISION.md](docs/VISION.md)**.
See **[docs/PROGRESS.md](docs/PROGRESS.md)** for the full progress report and hand-off notes.

---

## Read these first

| Document                                                        | What it covers                                                                          |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| [docs/PROGRESS.md](docs/PROGRESS.md)                            | What is done, what is verified, what is next, open questions. **Start here.**           |
| [docs/PRODUCT.md](docs/PRODUCT.md)                              | The product, the brand, plans and prices, Simple mode, business model, hard constraints |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)                    | Stack, folder map, how the site is rendered, database, conventions                      |
| [roadmap.md](roadmap.md)                                        | The live task list (checkboxes)                                                         |
| [AGENTS.md](AGENTS.md)                                          | Rules every human or AI contributor must follow                                         |
| [docs/VISION.md](docs/VISION.md)                                | One tech friend for everything: hooks, channels, native helper apps (Layers 2 and 3)    |
| [server/](server/README.md)                                     | **The Mindy server**: app + API + WhatsApp/Instagram/Telegram bots. Deploy: server/DEPLOY.md |
| [legacy/claude-launch-kit/](legacy/claude-launch-kit/README.md) | Older copy of the launch kit (superseded by `server/`, kept for history)                |

## Stack

Two parts, deployed separately:

1. **Website** (this folder's `src/`, synced with Lovable) — details below.
2. **Mindy server** (`server/`): Python FastAPI + SQLite + WebSockets + scheduler, serving the Mindy web app (PWA)
   at app.whatsonyourmind.online and the bots at api.whatsonyourmind.online. AI is rules-first, then the cheapest
   model through any OpenAI-compatible API (default Gemini 2.5 Flash-Lite). One Docker container + Caddy.
   `cd server && pip install -r requirements.txt && pytest -q` (31 tests).

Website stack:

- **TanStack Start v1** (React 19, file-based routing, server functions, SSR) on **Vite 7**
- **Tailwind CSS v4** (configured in `src/styles.css`) + shadcn/ui primitives
- **Lovable Cloud** backend (Postgres, auth, storage) — schema changes are made through Lovable
- Deploys to an edge runtime (Cloudflare Workers). Server code must be Worker-compatible, not Node-only.
- Tests: **Vitest** + Testing Library

## Run locally

```sh
bun install        # or npm install
bun run dev        # http://localhost:8080
bun run test       # vitest
bun run lint
```

`.env` holds only publishable (browser-safe) keys. Private secrets live in Lovable Cloud, never in the repo.

## Pages

| URL                  | Page                                               |
| -------------------- | -------------------------------------------------- |
| `/`                  | Home (WhatsApp first), plans and prices, waitlist  |
| `/whatsapp`          | Mindy on WhatsApp                                  |
| `/instagram`         | Mindy on Instagram                                 |
| `/app`               | The Mindy app (real screenshots)                   |
| `/privacy`, `/terms` | Legal (draft — needs lawyer review before launch)  |
| `/try/index.html`    | Clickable design tour with demo data (static file) |

## Working with Lovable

This repository is two-way synced with a [Lovable](https://lovable.dev) project. Commits pushed to the
synced branch appear in the Lovable editor. Do not force-push or rewrite pushed history, and do not hand-edit
`supabase/`, `drizzle/`, `src/routeTree.gen.ts` or `src/integrations/supabase/*` (all generated).
