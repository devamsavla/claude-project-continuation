# Progress report

_Last updated: 12 Nov 2026._ Keep this file current: update it at the end of every working session.

## TL;DR for the next builder

1. Stage 1 (website + design tour + waitlist) is **done and verified**.
2. **Decision 14 Nov 2026:** instead of porting the app to the Lovable stack, ship the working Python server.
   It now lives in **`server/`** and serves the real Mindy app + WhatsApp + Instagram + Telegram. The website's
   "Open the app" points at `https://app.whatsonyourmind.online` (`src/site/config.ts`).
3. Mindy became **one tech friend for everything** (see [VISION.md](VISION.md)): saves → real plans, family care,
   khata with UPI links, scam shield, do-it-for-me links (Uber, Maps, UPI), screenshot help, study help, file tools, Telegram.
4. Next: **deploy** (server/DEPLOY.md, Azure for Students), connect WhatsApp, then the native Android helper (Layer 2).

## Where it came from

The founder built whatsonyourmind / Mindy in the Claude desktop app as a "launch kit": brand assets, a static
website, a single-file design tour, and a FastAPI + SQLite backend with a vanilla-JS web app. It was never
launched — **there are no real users or data to migrate.** The agreed migration order is:

1. Website + design tour + waitlist → **done**
2. The real Mindy web app → **next**
3. Mindy on WhatsApp and Instagram → needs Meta app credentials from the founder

## Done

### Stage 1 — website (verified 11 Nov 2026)

- [x] Six pages ported pixel-identical from the original static site: `/`, `/whatsapp`, `/instagram`, `/app`, `/privacy`, `/terms`.
      Verified with side-by-side Playwright screenshots against the originals.
- [x] Site behaviour ported to `src/site/site-init.ts`: live reminder demo, notification "vibes", local-currency price picker, stamps, waitlist form.
- [x] Waitlist stored in the database through the `join_waitlist` function (validates email, de-duplicates, returns queue position). Tested: insert + duplicate.
- [x] Design tour served as a static file at `/try/index.html` (PWA manifest + service worker), back link points to `/`.
- [x] Per-page titles, descriptions and social share tags; brand fonts loaded in `src/routes/__root.tsx`.
- [x] Brand assets copied: `public/stickers`, `public/screens`, favicon, share image, WhatsApp QR.

### Business layer on the site (approved 11 Nov 2026)

- [x] Three plans shown: **Free forever**, **Mindy Plus**, **Mindy Care** — Plus and Care marked "after launch".
- [x] One-off extras and "Businesses pay too" income streams shown on home and app pages.
- [x] All prices in one file (`src/site/prices.ts`) for INR / USD / GBP / EUR / AED / BRL, guarded by tests.

## Next (in order)

1. **Stage 2 — real Mindy app at `/mindy`** (see roadmap 2a–2g)
   - Database schema ported from `db.py` + the extra tables `api.py` creates; RLS on every table.
   - Sign-in: **email + Google** (decided). WhatsApp number is linked later by texting Mindy a code.
   - Port `webapp/app.js`, `mindy.js`, `app.css`; replace `fetch('/api/...')` calls with server functions keeping the same JSON shapes as `api.py` (~45 endpoints).
   - Port `brain.py` parsing rules to TypeScript. **Rules first**; call the cheapest built-in AI model only when rules fail (decided — no Anthropic key).
   - Realtime chat / status / plans; game state (hand cricket, Last Card) stored in the database, never in server memory.
   - Scheduled reminder delivery + Web Push.
   - Then point `SITE.appUrl` in `src/site/config.ts` at `/mindy`.
2. **Simple mode** inside Mindy for older people (scope agreed — see PRODUCT.md).
3. **Plus value** (unlimited WhatsApp reminders, voice notes, bill photos, group reminders) — build before charging.
4. **Stage 3 — WhatsApp + Instagram bot** (port `handlers.py`, `whatsapp.py`, `instagram.py` to `src/routes/api/public/*` webhooks with signature checks).
5. **Payments** for Plus, Care and extras — only after launch, once the paid features work.

## Launch-readiness requirements (apply to everything)

The founder expects a traffic spike at launch. Every feature must:

- keep **no state in server memory** (Workers are stateless; use the database),
- rate-limit anything public or costly (waitlist, AI calls, WhatsApp sends),
- show friendly errors instead of crashing,
- be observable (log failures with enough context to debug).

## Open questions / placeholders (need the founder)

| Item                                                                    | Where                                   | Status                                                   |
| ----------------------------------------------------------------------- | --------------------------------------- | -------------------------------------------------------- |
| Real WhatsApp number                                                    | `src/site/config.ts` (`waNumber`)       | Placeholder `447700900000`                               |
| Instagram handle                                                        | `src/site/config.ts` (`igHandle`)       | Assumed `whatsonyourmind`                                |
| Company details, ICO registration                                       | `src/site/pages/privacy.ts`, `terms.ts` | Draft, needs lawyer review                               |
| 30 free WhatsApp reminders / month                                      | `src/site/prices.ts`                    | Proposed by AI, approved in memory — reconfirm at launch |
| "Waitlist gets 3 months of Plus free"                                   | home page copy                          | Proposed by AI — reconfirm                               |
| EUR / AED / BRL prices and new extras (photo book, plush, sticker pack) | `src/site/prices.ts`                    | Proposed by AI — reconfirm                               |
| "We never sell your data"                                               | home page copy                          | A promise — keep only if intended                        |
| Meta (WhatsApp/Instagram) app credentials                               | Lovable Cloud secrets                   | Needed for Stage 3                                       |

## Done on 14 Nov 2026 (server/)

- [x] Cheapest AI: rules first, then any OpenAI-compatible model (default Gemini 2.5 Flash-Lite), cache + per-person daily budget (`llm.py`)
- [x] Saves → real life: classify every save, one-tap actions, friend matches, Saved→Done score + streak (`hooks.py`)
- [x] Family care: family codes (also by WhatsApp "family 123456"), care reminders, "I took it" button or reply "took", missed-dose alerts, simple mode (`care.py`)
- [x] Khata with UPI pay links; do-it links (Uber, Maps, UPI, call, WhatsApp); scam shield with link checks + community reports; screenshot help with circles; homework help; privacy check-up; file tools (ffmpeg) (`skills.py`)
- [x] Telegram channel (free reminders, open chat, forwarded posts saved) (`telegram.py`)
- [x] Google sign-in (works before Meta approval)
- [x] Tests: 31 pytest (incl. multi-person live sockets, care loop, khata, scam, Telegram, file tools) + two-browser Playwright runs
- [x] Deploy kit: Dockerfile with ffmpeg, docker-compose + Caddy (auto HTTPS), one-script setup for Azure for Students

## Done later on 14 Nov 2026

- [x] WhatsApp moments: "where's my car" (pin + walking route + Street View + your photo), "take me home", home/office places, read-this-letter, voice notes understood (`places.py`)
- [x] Mindy buttons: personal one-tap home-screen buttons (I parked here, Where's my car, Take me home, SOS to family) at `/b/<key>/<action>`
- [x] **Android helper app** (`android/`): floating Mindy bubble, voice in Hindi/English, reads screen buttons as text, pulsing pointer + spoken step, opens apps at the right screen, "do it for me" mode, never touches PIN/OTP or pay buttons, "I'm stuck" alerts family. Server brain: `server/app/helper.py` (tested). APK builds in GitHub Actions (`.github/workflows/android.yml`) — **not compiled yet**: the first CI run is the compile check
- [x] Pitch deck "Just tell Mindy" (moments, not features), made in Claude

## Session log

| Date        | Work                                                                                                               |
| ----------- | ------------------------------------------------------------------------------------------------------------------ |
| 11 Nov 2026 | Migrated Stage 1 website, design tour and waitlist; verified pixel match                                           |
| 11 Nov 2026 | Agreed Stage 2 decisions, Simple mode scope, business model; raised prices; added plans and income streams to site |
| 12 Nov 2026 | Organised repo for hand-off: README, docs/, legacy reference folder, this report                                   |
| 14 Nov 2026 | Shipped server/ (real app + bots), tech-friend features, Telegram, Google sign-in, deploy kit; site points to the app |
