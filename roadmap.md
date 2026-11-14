# Roadmap

Live task list. Details and context: [docs/PROGRESS.md](docs/PROGRESS.md). Product rules: [docs/PRODUCT.md](docs/PRODUCT.md).

## Stage 1 — Website (done)

- [x] Website: home, WhatsApp, Instagram, app, privacy, terms (pixel-identical port)
- [x] Design tour at `/try/index.html`
- [x] Working waitlist form (database, de-duplicated, shows position)
- [x] Free / Plus / Care plans, extras and business income shown on the site (approved prices, tested)
- [x] Repo organised for hand-off: README, docs/, legacy reference, progress report

## Stage 2 — The real Mindy app (done, in `server/`)

Decided 14 Nov 2026: ship the tested Python server instead of porting. Sign-in: WhatsApp code or Google.

- [x] App: friends, live status, chats with @mindy, plans, watch parties, hand cricket, Last Card, Mind, passport, push
- [x] Saves → real life, friend matches, streak
- [x] Family care + simple mode; khata + UPI links; scam shield; do-it links; screenshot help; homework help; file tools
- [x] Telegram bot; Google sign-in
- [ ] **Deploy** to Azure for Students (server/DEPLOY.md) — founder: create VM, add DNS records, add keys
- [ ] Get Meta templates approved: mindy_reminder, mindy_care, mindy_care_alert, mindy_login_code

## Layer 2 / 3 — native helpers (see docs/VISION.md)

- [ ] Android helper: on-screen pointer over any app (accessibility overlay), do-it mode, caller ID + spam blocking, privacy scan
- [ ] iPhone helper: live screen guidance (ReplayKit + Picture-in-Picture + Live Activity), CallKit spam labels

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

- [x] Webhooks with signature checks; task-specific bot only (WhatsApp AI-chatbot policy) — in server/
- [ ] Message templates approved by Meta — **blocked: needs Meta app credentials from the founder**

## Business (after launch)

- [ ] Switch on payments for Plus, Care and extras once the features work
- [ ] Business streams: pharmacy refills, Mindy for businesses, care homes, bills/tickets/cafés passport
- [ ] Shop: photo books, plush, sticker packs

## Launch readiness (applies to all of the above)

- [ ] Holds up under a launch spike: no in-memory state, rate limits, friendly errors, monitoring
- [ ] Real WhatsApp number + Instagram handle in `src/site/config.ts` — **blocked: founder to supply**
- [ ] Company details, ICO registration, lawyer-checked privacy and terms — **blocked: founder to supply**
