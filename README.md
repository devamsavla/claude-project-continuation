# whatsonyourmind · Mindy

> Just text Mindy on WhatsApp: save anything, find it in plain words, get reminders in any time zone.
> Then the free Mindy app for friends, plans and games.

**Status:** pre-launch. The marketing website, design tour and waitlist are live in this codebase.
The real Mindy app (Stage 2) and the WhatsApp / Instagram bot (Stage 3) are next.
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
| [legacy/claude-launch-kit/](legacy/claude-launch-kit/README.md) | The original Python backend + web app to port in Stage 2 (reference only, not built)    |

## Stack

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
