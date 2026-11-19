# Put Mindy live (about 1 hour, ₹0 for the first year)

One small server runs everything: the Mindy app (app.whatsonyourmind.online), the API and the WhatsApp,
Instagram and Telegram bots (api.whatsonyourmind.online). The marketing website stays on Lovable.

## What you need (all free)

| Thing | Where | Time |
|---|---|---|
| A server | **Azure for Students** (azure.microsoft.com/free/students, sign in with your NYU email, no card) | 10 min |
| AI key | **Gemini**: aistudio.google.com → Get API key (free tier) | 2 min |
| Telegram bot | Telegram → @BotFather → `/newbot` → copy the token | 2 min |
| Google sign-in | console.cloud.google.com → APIs & Services → Credentials → OAuth client ID → Web application. Authorised JavaScript origin: `https://app.whatsonyourmind.online` | 5 min |
| WhatsApp | Meta for Developers (see README "Connect real WhatsApp") | 1–3 days for approval |

## 1. Create the server (Azure for Students)

1. Azure portal → **Create a resource → Virtual machine**.
2. Image **Ubuntu Server 24.04 LTS**, size **B1s** (free for 12 months on student accounts) or B2ats.
3. Authentication: **SSH public key** (let Azure generate one and download it).
4. Inbound ports: **SSH (22), HTTP (80), HTTPS (443)**.
5. Create. Copy the **public IP address**.

## 2. Point the domain at it

At your domain's DNS (where whatsonyourmind.online is managed), add two **A records** to the server's IP:
`api` and `app`. Wait a few minutes.

## 3. Install Mindy

```bash
ssh -i mindy_key.pem azureuser@<IP>
git clone https://github.com/devamsavla/claude-project-continuation.git
cd claude-project-continuation/server
bash deploy/setup-server.sh        # first run creates .env and stops
nano .env                          # fill in the keys (see below), save with Ctrl+O, exit Ctrl+X
bash deploy/setup-server.sh        # builds and starts Mindy with HTTPS
curl https://api.whatsonyourmind.online/health
```

Minimum `.env` to launch the app and Telegram today:

```
LLM_API_KEY=<gemini key>
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_WEBHOOK_SECRET=<any long random text>
TELEGRAM_BOT_USERNAME=<your bot's username>
GOOGLE_CLIENT_ID=<web client id>.apps.googleusercontent.com
ADMIN_KEY=<long random text>
PUBLIC_WA_NUMBER=<Mindy's WhatsApp number, digits only>
DEV_CODES=0
ALLOWED_ORIGINS=https://whatsonyourmind.online,https://app.whatsonyourmind.online
```

## 4. Switch on Telegram (1 command)

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://api.whatsonyourmind.online/webhook/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

Message your bot: it answers. Send "link" in the app (Me → Telegram) to join accounts.

## 5. Switch on WhatsApp and Instagram

Follow `README.md` ("Connect real WhatsApp", "Connect Instagram") and submit the templates in `TEMPLATES.md`
(`mindy_reminder`, `mindy_care`, `mindy_care_alert`, `mindy_sos`, `mindy_login_code`). Add the keys to `.env` and run
`bash deploy/setup-server.sh` again.

## Before you connect WhatsApp: the number

Meta's WhatsApp Business Platform needs a number that is **not** active in the normal WhatsApp or WhatsApp Business
app. If +44 7391 325727 is your personal WhatsApp, either move it to the platform (your chats on that number stop working
in the phone app) or get a second SIM for Mindy and put its number in `PUBLIC_WA_NUMBER` and `src/site/config.ts`.
Until WhatsApp is approved, launch on **Telegram + the app** (steps 3 and 4): both need no approval.

## 6. Optional extras

Each of these is off until you add its key. Run `bash deploy/setup-server.sh` after editing `.env`.

**Voice replies.** Google Cloud console → enable *Cloud Text-to-Speech API* → Credentials → API key → `TTS_API_KEY`.
Free tier covers millions of characters a month. Without it Mindy uses the offline `espeak-ng` voice (robotic but free).

**Virtual try-on.** Uses Gemini's image model. If `LLM_BASE_URL` is already Gemini, nothing to add; otherwise set
`GEMINI_API_KEY`. Each image costs about $0.04, so `TRYON_DAILY` caps it per person.

**Forward emails to Mindy.** Needs the domain's DNS on Cloudflare (free plan).
1. Cloudflare → whatsonyourmind.online → Email → Email Routing → enable for the subdomain in `EMAIL_DOMAIN`.
2. Workers → Create → paste `deploy/email-worker.js` (add the `postal-mime` package), set `MINDY_URL` and `MINDY_SECRET`.
3. Email Routing → Routing rules → Catch-all → Send to a Worker → the worker.
People get their address by saying "connect email" to Mindy.

**Calendar.** Nothing to set up: "connect calendar" gives each person a private feed URL to add to Google/Apple Calendar.

**Missed-call and SMS line (basic phones).** A spare Android phone with a cheap prepaid SIM:
1. Install the Mindy helper APK (GitHub → Actions → *android helper apk* → artifact) on that phone.
2. Open it → Advanced → put the server URL and `GATEWAY_SECRET` → *Gateway mode on*. Allow SMS and phone permissions.
3. Keep it charged and on Wi-Fi. Give its number out as "give a missed call to Mindy". Normal SMS rates apply on that SIM.

**WhatsApp Flow (a family-tree form inside WhatsApp).** WhatsApp Manager → Account tools → Flows → Create flow →
paste `flows/add_person.json` → Publish. Put the Flow ID in `WA_FLOW_PERSON_ID`. Without it, Mindy links to the app instead.

**iPhone clipboard.** Nothing on the server. Each person follows the steps on the app's Clipboard screen
(Shortcuts → Get Clipboard → Get Contents of URL → their private link → Back Tap).

**Caller ID on Android.** In the helper app: *Turn on scam caller warnings* (Android 10+). No contacts are uploaded;
only the incoming number is checked against community reports.

## Updating

```bash
cd claude-project-continuation && git pull && cd server && bash deploy/setup-server.sh
```

## Costs

| Item | Cost |
|---|---|
| Server (Azure for Students B1s) | free for 12 months, then about $8/month (or move to Heroku/Render) |
| AI (Gemini Flash-Lite) | free tier, then about $0.10 per million words read; rules handle most messages for free |
| Telegram | free |
| WhatsApp | replies within 24 h free; reminders after 24 h are paid templates (cheap utility rates, per country) |
| HTTPS | free (Caddy + Let's Encrypt) |

## Secrets

Keep `.env` only on the server. If you use **Doppler** (free with the GitHub Student Pack), store the keys there
and run `doppler run -- docker compose -f deploy/docker-compose.yml up -d --build` instead.

## Backups

The database is one file in the `mindy-data` Docker volume. Daily backup:
`docker run --rm -v deploy_mindy-data:/data -v $HOME:/b alpine cp /data/mindy.db /b/mindy-$(date +%F).db`
