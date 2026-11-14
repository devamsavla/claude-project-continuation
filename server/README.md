# whatsonyourmind backend

The server behind **Mindy** on WhatsApp, on Instagram and in the **Mindy web app**. It also serves the web app
itself (folder `webapp/`), so one deploy gives you all three. One brain, three front doors: it receives messages from
the WhatsApp Cloud API and Instagram messaging, saves what people send (reels shared on Instagram
included), finds it again, runs reminders (including from photos of tickets and invitations), keeps lists
and birthdays, links the same person across WhatsApp, Instagram and the app, and powers the waitlist form
on whatsonyourmind.online.

```
WhatsApp user ──▶ Meta Cloud API ──▶ POST /webhook ───────────┐
Instagram user ─▶ Instagram API ───▶ POST /webhook/instagram ─┤
                                                              ▼
                                                  Mindy (FastAPI): one brain
                                                  ├─ Rules first, then the cheapest AI model (llm.py)
                                                  ├─ SQLite + full-text search: memory
                                                  ├─ accounts: one person, many channels (send LINK)
                                                  └─ Scheduler: reminders every 30 s, birthdays daily,
                                                     sent on the channel that can still reach them
website form ──▶ POST /api/waitlist
Mindy web app ─▶ GET /  (static files in webapp/)  +  /api/*  (REST)  +  /ws  (live socket)
```

## What works today

| You send | Mindy does |
|---|---|
| any text, link or Instagram reel | saves it into a collection (Reels, Links, Notes, Food spots...) and reacts 🧠 |
| `what was that pasta place?` | full-text search over everything saved, answered in one to three lines |
| `remind me to call mum tomorrow at 6pm` | reminder in your timezone with Cancel / All reminders buttons |
| `remind me to pay rent on 1 dec every month` | repeating reminder |
| a photo of a ticket or invitation | reads the date and sets a reminder two hours before |
| `add milk, eggs to shopping list` / `show shopping list` | lists |
| `Sofia's birthday is 12 March` | nudge the day before with a drafted message |
| `upcoming`, `export my data`, `delete my data`, `timezone Europe/Paris` | exactly that |
| (Instagram) a shared reel or post | saved to Reels / Instagram with its caption and link, findable from any channel |
| `link` on one app, then `link 123456` on the other | joins WhatsApp and Instagram into one Mindy |
| (Sunday 18:00) | a weekly summary for anyone who saved something that week |

Reminders due when the user has been quiet for 24 hours go out as an approved template (see `TEMPLATES.md`),
which is what WhatsApp requires.

## Mindy, the tech friend (all channels)

| Send | Mindy does |
|---|---|
| a reel or link | understands it (recipe, place, workout, study, product, trip) and offers one-tap actions: shopping list + cook reminder, plan with friends, weekly workout, quiz |
| `book an uber to Phoenix Mall` | one button that opens Uber with the drop filled in (also directions, calls, WhatsApp chats) |
| `pay ₹500 to name@okaxis` | a tap-to-pay UPI link (through `/go`, since chat apps only link https) |
| `Ramesh owes me 500`, `paid Sunil 300`, `khata`, `remind Ramesh` | khata balances; a ready WhatsApp reminder with your UPI link (`my upi is you@bank` once) |
| any suspicious message or link, or `is this a scam?` | verdict with reasons (patterns, look-alike bank sites, .apk, short links, community reports); `report` to warn everyone |
| a screenshot + `where do I tap?` | the screenshot back with a circle on the spot and the next step |
| a video with `mp3` or `compress` | converted file back (ffmpeg) |
| `family 123456` | links with family; they can set care reminders; reply `took` or tap "I took it"; family alerted if missed |
| anything else, on Telegram | open answers (cheap model). On WhatsApp Mindy stays task-specific, as WhatsApp requires |

AI is rules-first; only unclear messages, saves and photos go to the cheapest model (`app/llm.py`, default
Gemini 2.5 Flash-Lite, any OpenAI-compatible API), with a cache and a per-person daily budget. Deploy: `DEPLOY.md`.

## The Mindy web app

A real app, not a mock-up: open `/` and sign in with a WhatsApp number. It's a Progressive Web App, so people
add it to their home screen and it opens full screen. No app store.

| In the app | How it works |
|---|---|
| **Sign in with WhatsApp** | type your number, Mindy sends a 6-digit code on WhatsApp (text inside 24 h, `mindy_login_code` template outside), or send `login` to Mindy. Sessions are random tokens; only their SHA-256 is stored. Codes last 10 minutes and are rate-limited |
| **Same memory** | the app account *is* your WhatsApp account, so everything you sent Mindy is there, and what you add in the app is findable on WhatsApp |
| **Friends** | invite links (`/?invite=…`); live presence and status (free, studying, gaming, at the match, busy, ghost) |
| **Chats** | one-to-one and groups over the live socket; `@mindy` in a chat plans, splits or reminds for everyone |
| **The bubble** | one sentence → plan with invites, reminder, list, birthday, save or answer |
| **Plans** | invites, RSVP (going, maybe, can't) |
| **Watch parties** | YouTube synced play/pause/seek for everyone, reactions, chat; for Netflix, Prime and co a shared link and a synced 3·2·1 |
| **Games** | hand cricket (1v1 vs a friend or Mindy) and Last Card (2–4), server-side engines in `app/games.py` |
| **Mind** | reminders (done, snooze), saves with search and collections, lists, birthdays, a daily mood check-in, charts, passport stamps |
| **Notifications** | live in the app; phone notifications by Web Push (VAPID keys made automatically); WhatsApp. Each person chooses app, WhatsApp or both |
| **Your data** | download everything, delete the account |

Local try-out: run the server (below) and open http://localhost:8000. With WhatsApp not connected, the sign-in code
is shown on screen (`DEV_CODES=1`). Open a second browser profile to be a second person and test chats and games.

## Run it locally (5 minutes, no Meta account needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # leave WA_TOKEN empty for dry-run mode
export $(grep -v '^#' .env | xargs)
pytest -q                       # 31 tests: parsing, webhooks, reminders, games, the app live, care, khata, scam, Telegram, files
uvicorn app.main:app --reload
```

Without `WA_TOKEN` messages are printed to the log instead of sent. Without `LLM_API_KEY` a
built-in rules parser handles every core command, so you can demo it offline.

## Connect real WhatsApp

1. **Meta app.** developers.facebook.com > Create app > type *Business* > add the **WhatsApp** product.
   You get a free test number straight away.
2. **Token.** Business settings > System users > add an admin system user > generate a token with
   `whatsapp_business_messaging` and `whatsapp_business_management`. Put it in `WA_TOKEN`.
   Copy the **Phone number ID** into `WA_PHONE_NUMBER_ID` and the **App secret** into `WA_APP_SECRET`.
3. **Deploy** (below) so you have an HTTPS URL, e.g. `https://api.whatsonyourmind.online`.
4. **Webhook.** WhatsApp > Configuration > Callback URL `https://api.whatsonyourmind.online/webhook`,
   Verify token = your `WA_VERIFY_TOKEN`. Subscribe to the **messages** field.
5. **Templates.** Submit the templates in `TEMPLATES.md`; approval usually takes minutes to a day.
6. **Go live.** Add your real number, complete **Business verification** and the display name review to
   lift the test limits. Check pricing in WhatsApp Manager: replies inside 24 hours are free,
   utility templates are charged per message.

## Connect Instagram

1. In the same Meta app, add **Instagram** > *API setup with Instagram login* and connect the
   whatsonyourmind Instagram **professional** account (business or creator).
2. Generate a token with `instagram_business_basic` and `instagram_business_manage_messages`;
   put it in `IG_TOKEN`, the account ID in `IG_USER_ID`, the Instagram app secret in `IG_APP_SECRET`.
3. Webhooks: callback `https://api.whatsonyourmind.online/webhook/instagram`, verify token `IG_VERIFY_TOKEN`,
   subscribe to **messages**.
4. To answer people who aren't testers on your app, submit **App Review** for
   `instagram_business_manage_messages` (screencast of the DM flow, privacy policy URL).
   This usually takes days to a few weeks.

Instagram's rules, built in: Mindy can only reply within 24 hours of the person's last message, there are no
templates, text is capped at 1,000 bytes and group chats aren't supported. So Instagram is the capture inbox
(share reels, ask questions), and reminders go out on WhatsApp or the app. People link the two by sending
`link`. A reminder for someone on Instagram only, outside the 24 hours, is marked `undelivered` (counted on
the admin page) rather than silently dropped.

## Deploy

- **Render:** push this folder to GitHub, New > Blueprint, pick the repo (`render.yaml` is included,
  with a 1 GB disk for the database). Point both `api.whatsonyourmind.online` and `app.whatsonyourmind.online`
  at it with CNAMEs (same service: the API, the live socket and the app's files).
- **One server only.** Live features (presence, games, watch parties) keep their state in the server's memory,
  so run a single instance. That's fine for many thousands of people; scaling out later means adding Redis.
- **Anywhere with Docker:** `docker build -t mindy . && docker run -p 8000:8000 --env-file .env -v mindy:/data mindy`
- **Railway / Fly.io:** same Dockerfile; mount a volume at `/data`.

## Website waitlist

`POST /api/waitlist` with `{"email": "...", "interest": "whatsapp|app|both"}` returns your position.
The website already calls it; set `ALLOWED_ORIGINS` to your domain. See your numbers and the latest
sign-ups at `https://api.whatsonyourmind.online/admin?key=ADMIN_KEY` (JSON at `/admin/stats`).

## Rules to stay on the right side of

- **WhatsApp's AI policy.** Since 15 January 2026 the WhatsApp Business Solution terms bar
  general-purpose AI chatbots. Mindy is scoped to memory, reminders, lists and occasions, and the
  system prompt declines anything else. Keep it that way.
- **Opt-in.** Only message people who messaged you first or opted in on the website.
- **UK GDPR.** Register with the ICO and pay the data protection fee, publish a privacy policy, and keep
  `export my data` / `delete my data` working (both are built in).
- **Groups.** The Cloud API Groups API needs an Official Business Account and supports small groups;
  group handling is the next milestone (`handlers.py` is structured for it).

## Project layout

```
app/
  main.py       FastAPI routes: webhooks, waitlist, admin, /ws live socket, the web app's files, scheduler
  api.py        the web app's REST API (/api/...)
  auth.py       sign in with WhatsApp: codes, sessions, the app's tables
  realtime.py   live hub: presence, chat delivery, games, watch parties, Web Push
  games.py      hand cricket and Last Card engines
  handlers.py   one inbound message -> Mindy's reply; reminder and birthday jobs
  brain.py      rules parser, date parsing, save classifier; AI only when rules can't tell
  llm.py        one OpenAI-compatible client with cache and daily budget (default Gemini Flash-Lite)
  hooks.py      saves become real: actions, friend matches, score and streak
  care.py       family links, care reminders, "I took it", missed-dose alerts
  skills.py     do-it links, khata, scam shield, link checks, screenshot help, file tools
  telegram.py   Telegram client and update normaliser
  whatsapp.py   Cloud API client: text, buttons, lists, templates, reactions, media, signature check
  db.py         SQLite schema, full-text search, export and delete
webapp/         the Mindy web app: index.html, app.js, app.css, sw.js (offline + push), manifest
tests/          pytest suite (runs in dry-run mode)
```

## Next milestones

1. Voice notes: add a speech-to-text provider in `handlers.on_media`.
2. Groups: polls, shared lists and plans when Mindy is added to a group.
3. Semantic search: add embeddings next to the full-text index.
4. Snap to shop: product search API for clothing photos.
5. Move SQLite to Postgres once you pass about 10k active users.
