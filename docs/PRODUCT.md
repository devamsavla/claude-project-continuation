# Product

## In one line

**Mindy** is a friendly memory and reminders companion you reach first on WhatsApp, then in the free Mindy app
for friends, plans and games. The company / site is **whatsonyourmind** (whatsonyourmind.online).

**North star:** people remember what matters and the plans they make with friends happen.
**Metric:** reminders delivered to people each day.

## Brand

- Names: **whatsonyourmind** (company, site) and **Mindy** (the character and the app).
- Look: dark sticker-zine style, WhatsApp green `#25D366` as the accent.
- Fonts: Bricolage Grotesque (display), Figtree (body), Instrument Serif (accents), JetBrains Mono (labels).
- Mascot: Mindy in 9 moods — stickers in `public/stickers`.
- Tone: warm, short, a little playful. Never preachy.

## Launch order

1. **WhatsApp first** — text Mindy to save things and get reminders.
2. **The Mindy app** — friends, chats with @mindy, plans, watch parties, games, passport.
3. **Instagram** — DM Mindy.

Global from day one: UK + India + everywhere, with local currencies and fair local prices.

## Hard constraints

- **WhatsApp policy:** since 15 Jan 2026 WhatsApp bars general-purpose AI chatbots. Mindy on WhatsApp must stay
  **task-specific** (memory and reminders). Never market or build it as "chat with an AI about anything".
- **Medications:** Mindy reminds and reads labels aloud; it **never gives medical advice**.
- **Data:** never sell user data; no ads inside chats.
- **Value first:** launch free. Paid plans switch on only **after launch**, once their features really exist.

## Plans and prices (approved 11 Nov 2026)

Source of truth: `src/site/prices.ts` (all currencies). Tests in `src/test/prices.test.ts` lock these.

| Plan                   | INR  | GBP   | USD   | What you get                                                                                                                   |
| ---------------------- | ---- | ----- | ----- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Free forever**       | ₹0   | £0    | $0    | Save, search, unlimited in-app reminders, 30 WhatsApp reminders a month                                                        |
| **Mindy Plus** / month | ₹99  | £2.99 | $3.49 | Unlimited WhatsApp reminders, voice notes → reminders, bill & ticket photos, reminders in WhatsApp groups, full-quality albums |
| **Mindy Care** / month | ₹199 | £4.99 | $5.99 | Plus for a parent + Simple mode family features (missed-dose alerts, ask family), up to 5 family members, giftable             |

Waitlist members get 3 months of Plus free (to reconfirm). Why WhatsApp usage is paid: every WhatsApp message Mindy sends costs money.

### One-off extras

| Extra                                                  | INR    | GBP   | USD   |
| ------------------------------------------------------ | ------ | ----- | ----- |
| Afterglow Forever (keep one album in full quality)     | ₹149   | £2.99 | $3.99 |
| Holo sleeve for your rarest card                       | ₹49    | £0.99 | $0.99 |
| League pass (auction night for 10 friends, per season) | ₹299   | £4.99 | $5.99 |
| Printed Group Wrapped zine                             | ₹699   | £14   | $18   |
| Hardback photo book                                    | ₹1,499 | £29   | $35   |
| Sticker pack                                           | ₹79    | £1.49 | $1.49 |
| Mindy plush toy                                        | ₹999   | £19   | $24   |

### Business income streams (approved)

- **Pharmacy refills** — partner pharmacies when a medicine reminder runs low.
- **Mindy for businesses** — salons, clinics, tutors send reminders to their customers.
- **Care homes** — licence per resident for Simple mode + family alerts.
- **Bills, tickets, cafés** — deals and the cafés passport (partners pay per verified visit, no ads).

## Simple mode (agreed scope)

A switch inside the Mindy app (same account) for older people who find phones hard. Big buttons, voice-first.

- **Screenshot help:** send a screenshot and ask out loud; Mindy circles where to tap and reads the steps aloud one by one.
- **Ask family:** one tap sends the screenshot + question to a relative, who draws on it and sends it back.
- **Pointer inside Mindy:** a friendly animated pointer shows where to tap in the Mindy app itself.
- **Medications:** big spoken reminders with "I took it"; tell family if a dose is missed; photo of the box reads name and dose aloud and sets reminders.

Why there is no "Clicky-style" pointer over other phone apps: a website or web app cannot see or draw over other apps.
iPhone forbids it entirely; Android would need a separate native accessibility app.

## Feature backlog (wanted)

Photos + Afterglow albums, Family Care dashboard, voice notes, WhatsApp group reminders, scam checker, SOS to family,
letters/bills photo → reminders, remind-a-friend, Group Wrapped, chat translation, app in many languages.

## Decisions log

| Decision            | Choice                                                  | Why                                                                          |
| ------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| App sign-in         | Email + Google                                          | Works on day one without Meta approval; WhatsApp number linked later by code |
| AI                  | Rules-first parser, cheapest built-in model as fallback | Most messages are simple dates/lists; keeps costs near zero                  |
| Older-people helper | Simple mode inside Mindy, not a separate app            | One account, family can share Care plan                                      |
| Pricing             | Free + Plus + Care + extras + business streams          | Users never pay to remember; heavy WhatsApp use and family care pay          |
