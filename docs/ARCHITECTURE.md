# Architecture

## Stack

| Layer     | Choice                                                                                                             |
| --------- | ------------------------------------------------------------------------------------------------------------------ |
| Framework | TanStack Start v1 (React 19, SSR, file-based routes, `createServerFn`)                                             |
| Build     | Vite 7                                                                                                             |
| Styling   | Tailwind CSS v4 via `src/styles.css` (design tokens) + shadcn/ui. The marketing site uses its own CSS (see below). |
| Backend   | Lovable Cloud: Postgres + auth + storage. Browser client: `@/integrations/supabase/client`                         |
| Runtime   | Edge (Cloudflare Workers). No Node-only APIs in server code; no in-memory state.                                   |
| Tests     | Vitest + Testing Library (`src/**/*.test.ts(x)`)                                                                   |

## Folder map

```text
.
├── README.md                  Project front page
├── AGENTS.md                  Rules for every contributor (human or AI)
├── roadmap.md                 Live task list
├── docs/
│   ├── PROGRESS.md            Progress report + hand-off notes (start here)
│   ├── PRODUCT.md             Product, brand, prices, constraints, decisions
│   └── ARCHITECTURE.md        This file
├── legacy/claude-launch-kit/  Original FastAPI backend + vanilla-JS app to port (reference only)
├── public/
│   ├── try/                   Design tour: one static HTML file + PWA manifest + service worker
│   ├── stickers/  screens/    Brand stickers and app screenshots used by the site
│   └── favicon.png og-image.png qr-whatsapp.svg robots.txt
├── src/
│   ├── routes/                One file per URL (see README "Pages"); __root.tsx = shell, fonts, meta
│   ├── site/                  The marketing site
│   │   ├── pages/*.ts         Each page's original HTML as a string — edit copy here
│   │   ├── site.css legal.css Original site styles (with a revert block, see below)
│   │   ├── site-init.ts       Site behaviour: demo, vibes, price picker, stamps, waitlist form
│   │   ├── prices.ts          All plan + extra prices per currency — change prices here only
│   │   ├── config.ts          WhatsApp number, Instagram handle, "Open the app" URL
│   │   └── head.ts            Per-page title/description/share tags + stylesheet link
│   ├── components/site/SitePage.tsx   Renders a page's HTML and calls initSite()
│   ├── components/ui/         shadcn/ui primitives (for the upcoming app)
│   ├── integrations/supabase/ GENERATED — do not edit
│   ├── test/                  Vitest tests (routing, prices)
│   └── styles.css             Tailwind v4 theme + tokens
├── supabase/  drizzle/        GENERATED schema/migrations — change via Lovable only
└── src/routeTree.gen.ts       GENERATED route tree
```

## How the marketing site works

The site was hand-built as static HTML. To keep it pixel-identical:

1. Each route (e.g. `src/routes/index.tsx`) imports the page HTML string from `src/site/pages/` and renders it with `SitePage`.
2. `head()` uses `siteHead()` to set title/meta and link the page's stylesheet (`site.css` or `legal.css`).
3. After mount, `SitePage` calls `initSite()` which wires up the interactive bits.
4. Each site stylesheet starts with a zero-specificity `:where(.site-root)` revert block, because Tailwind's
   base reset would otherwise change the site's spacing, lists and widths.

**To change copy:** edit `src/site/pages/<page>.ts`. **To change prices:** edit `src/site/prices.ts` and update the tests.

## Database

| Object                                          | Purpose                                                            | Access                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------ |
| `public.waitlist`                               | Emails from the sign-up form (email, interest, source, created_at) | RLS on, **no client policies**                         |
| `public.join_waitlist(email, interest, source)` | Validates, de-duplicates, inserts; returns `(is_new, position)`    | `SECURITY DEFINER`, executable by anon + authenticated |

Visitors can join and see their position but can never read other emails.
Schema changes are made through Lovable (migrations land in `drizzle/` / `supabase/`).

## Conventions for new work (Stage 2 onward)

- The app lives under `/mindy` with Tailwind + design tokens (no hardcoded colours); protected pages under an `_authenticated` layout.
- App-internal server logic: `createServerFn`. Webhooks / cron / external callers: `src/routes/api/public/*`, and the handler must verify the caller (e.g. Meta signature).
- Initial data: route `loader` + `ensureQueryData`, component `useSuspenseQuery`.
- Every new table: RLS enabled, explicit policies and grants. User IDs as plain UUIDs (no FK to `auth.users` except `profiles` / `user_roles`). Roles in a separate `user_roles` table.
- Keep JSON shapes identical to `legacy/claude-launch-kit/backend/app/api.py` when porting, so `app.js` logic ports with minimal change.
- Add a small test for every business rule (prices, limits, permissions, dates).
