# Roadmap

Live task list. Details and context: [docs/PROGRESS.md](docs/PROGRESS.md). Product rules: [docs/PRODUCT.md](docs/PRODUCT.md).

## Stage 1 — Website (done)

- [x] Website: home, WhatsApp, Instagram, app, privacy, terms (pixel-identical port)
- [x] Design tour at `/try/index.html`
- [x] Working waitlist form (database, de-duplicated, shows position)
- [x] Free / Plus / Care plans, extras and business income shown on the site (approved prices, tested)
- [x] Repo organised for hand-off: README, docs/, legacy reference, progress report

## Stage 2 — The real Mindy app at `/mindy` (next)

Decided: email + Google sign-in; rules-first parsing with the cheapest built-in AI model as fallback.

- [ ] 2a Database: profiles (name, tz, status, notify, hue), friends, invites, chats, chat members, messages, items (+ search), reminders, lists, occasions, moods, stamps, plans, plan people, push subscriptions, link codes, channel accounts
- [ ] 2b Sign-in page (email + Google), profile on sign-up, invite links
- [ ] 2c Port `app.js` / `mindy.js` / `app.css`; API calls become server functions with the same JSON shapes as `api.py`
- [ ] 2d Port `brain.py` rules (dates, reminders, lists, birthdays, plans, money) to TypeScript; AI only when rules fail
- [ ] 2e Live updates (chat, status, plans); hand cricket + Last Card state in the database
- [ ] 2f Scheduled reminder delivery + phone notifications (Web Push)
- [ ] 2g Admin numbers page, export and delete my data; point "Open the app" (`src/site/config.ts`) at `/mindy`

## Simple mode — for older people (scope agreed)

- [ ] Big-button, voice-first switch in the same app and account
- [ ] Screenshot help: Mindy circles where to tap and reads steps aloud
- [ ] Ask family: one tap sends screenshot + question; family draws on it and sends back
- [ ] Pointer inside Mindy: animated pointer shows where to tap
- [ ] Medications: spoken reminders + "I took it"; family told if a dose is missed; box photo reads name/dose and sets reminders (no medical advice)

## Plus value and growth features

- [ ] Plus: unlimited WhatsApp reminders, voice notes, bill/ticket photos, group reminders, full-quality albums
- [ ] Photos + Afterglow albums
- [ ] Family Care dashboard, scam checker, SOS to family
- [ ] Letters/bills photo → reminders, remind-a-friend, Group Wrapped, chat translation, many languages

## Stage 3 — Mindy on WhatsApp and Instagram

- [ ] Webhooks with signature checks; task-specific bot only (WhatsApp AI-chatbot policy)
- [ ] Message templates approved by Meta — **blocked: needs Meta app credentials from the founder**

## Business (after launch)

- [ ] Switch on payments for Plus, Care and extras once the features work
- [ ] Business streams: pharmacy refills, Mindy for businesses, care homes, bills/tickets/cafés passport
- [ ] Shop: photo books, plush, sticker packs

## Launch readiness (applies to all of the above)

- [ ] Holds up under a launch spike: no in-memory state, rate limits, friendly errors, monitoring
- [ ] Real WhatsApp number + Instagram handle in `src/site/config.ts` — **blocked: founder to supply**
- [ ] Company details, ICO registration, lawyer-checked privacy and terms — **blocked: founder to supply**
