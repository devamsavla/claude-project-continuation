# Deploying whatsonyourmind

How the pieces fit, how to put each one live, what it costs, and what works on day one.

## The pieces

```
whatsonyourmind.online            the website (static files, folder: website/). Leads with WhatsApp.
whatsonyourmind.online/try/       a clickable tour of the app design (demo data)
app.whatsonyourmind.online        the real Mindy web app (served by the backend)
api.whatsonyourmind.online        the backend (folder: backend/), same server as app.
   ├─ /webhook                    Mindy on WhatsApp   (Meta WhatsApp Cloud API)
   ├─ /webhook/instagram          Mindy on Instagram  (Instagram API with Instagram Login)
   ├─ /api/…  and  /ws            the web app's data and live socket
   ├─ /api/waitlist               the website's updates form
   └─ /admin?key=…                your numbers
```

One backend serves WhatsApp, Instagram and the app. The app signs people in with their WhatsApp number, so it's
the same account automatically. Instagram is joined by sending `link`.

**Marketing order:** WhatsApp first (nothing to install, it's where people already are), then the app for friends,
plans and games. The website, the WhatsApp replies (`login` gives an app code) and the app all follow that order.

## Step by step

### Day 1: the website (about 30 minutes)
1. Open `website/assets/site.js` and change the two settings at the top:
   `WA_NUMBER` (your WhatsApp Business number, digits only) and `IG_HANDLE` (your Instagram username).
   Also change `+44 7700 900000` in `website/whatsapp.html` and regenerate `qr-whatsapp.svg` for your number
   (any QR generator, pointing at `https://wa.me/<number>?text=Hi%20Mindy!`).
2. Create a free Cloudflare account, go to **Workers & Pages → Create → Pages → Upload assets**, and drag in the
   `website/` folder. (Netlify or Vercel work the same way.)
3. **Custom domains → whatsonyourmind.online**. Cloudflare shows the DNS records; add them where you bought the
   domain (or move the domain's nameservers to Cloudflare, which is easiest). HTTPS is automatic.
4. Fill in the bracketed company details in `privacy.html` and `terms.html`.

### Day 1: the backend (about 1 hour)
1. Put the `backend/` folder in a private GitHub repository.
2. On render.com: **New → Blueprint**, pick the repo. `render.yaml` creates the service with a 1 GB disk.
3. Fill in the secret values when Render asks (you can leave WhatsApp and Instagram empty for now; it runs in
   test mode and logs messages instead of sending them).
4. **Settings → Custom domain**: add `api.whatsonyourmind.online` and `app.whatsonyourmind.online`, and the CNAMEs
   it shows at your DNS. Set `PUBLIC_WA_NUMBER` to Mindy's WhatsApp number (digits only).
5. Open `https://api.whatsonyourmind.online/health`. You should see `"ok": true`.
6. Open `https://app.whatsonyourmind.online`. Until WhatsApp is connected, set `DEV_CODES=1` for a test run
   (codes show on screen), then set it back to `0`.
7. Try the updates form on the website, then open `/admin?key=<ADMIN_KEY>`.

### Day 2: WhatsApp
Follow "Connect real WhatsApp" in `backend/README.md`. In short: a Meta app with WhatsApp, a permanent token,
webhook `https://api.whatsonyourmind.online/webhook`, subscribe to **messages**, submit the templates in
`backend/TEMPLATES.md` (including `mindy_login_code`, an Authentication template for app sign-in codes).
Message the test number from your own phone and Mindy answers. Send `login` and sign in to the app with the code.
Start **Business verification** the same day; it can take several days.

### Day 3: Instagram
Follow "Connect Instagram" in `backend/README.md`: a professional Instagram account, Instagram API setup with
Instagram login, webhook `https://api.whatsonyourmind.online/webhook/instagram`, then **App Review** for
`instagram_business_manage_messages`. Until review passes, only people you add as testers can use Mindy on
Instagram. Review usually takes from a few days to a few weeks and needs a screen recording of the flow.

### Day 3: the AI
Add `ANTHROPIC_API_KEY` in Render. Without it, Mindy still works with its built-in rules (reminders, lists,
birthdays, search); with it, Mindy understands free-form messages, answers questions and reads photos.

### Week 2: soft launch
Invite 20 friends. Watch `/admin` daily: messages, reminders sent, reminders undelivered, sign-ups.
Fix what confuses people, then post the Instagram launch grid.

## What it costs to run (first months)

| Item | Cost |
|---|---|
| Website hosting (Cloudflare Pages) | free |
| Backend (Render starter instance + 1 GB disk) | about $7–8 a month |
| WhatsApp: replies within 24 hours of the user's message | free |
| WhatsApp: reminders sent after 24 hours (utility templates) | charged per message, price depends on the country; see WhatsApp Manager |
| Instagram messaging API | free |
| Claude API | pay per use; small for a few hundred users, grows with usage |
| Domain | already owned |
| ICO data protection fee (UK) | yearly, by company size |

## Will it work perfectly?

Not "perfectly", and nobody's launch does. Here is exactly what is real today and what still needs doing.

| Part | Works on day one? | What's still needed |
|---|---|---|
| Website, 4 pages + legal | **Yes.** Static files; checked at desktop and phone widths with no errors. Every app screen on it is a screenshot of the real app | Your real number, Instagram handle and company details |
| Mindy web app | **Yes.** Sign in with WhatsApp, friends by invite link, live status, chats with @mindy, plans, watch parties, hand cricket, Last Card, reminders, saves, lists, charts, passport, phone notifications, export and delete. Tested with automated multi-person tests (3 people over live sockets) and two real browsers playing each other | WhatsApp connected for real sign-in codes; `mindy_login_code` template approved |
| Updates form | **Yes**, once the backend is live | `ALLOWED_ORIGINS` set to your domain (already in `render.yaml`) |
| Mindy on WhatsApp | **Yes, the core.** 16 automated tests pass using simulated Meta messages: saving, search, reminders in any time zone, repeats, lists, birthdays, photos, linking, template fallback after 24 hours | Testing with a real number; Meta business verification; templates approved. Not built yet: voice-note transcription, WhatsApp group chats, a download link for "export my data" |
| Mindy on Instagram | **Yes, the core**, tested with simulated Instagram webhooks: shared reels and posts are saved, questions answered, quick replies, linking | Meta App Review before the public can use it. Check the first real webhooks, because Meta changed the post-share format in 2025–26 (the code handles the old and new shapes). By Instagram's rules, reminders can't be sent there after 24 hours, so they go to WhatsApp or the app |
| AI understanding | **Yes** with a Claude API key; rules fallback without one | Tuning prompts with real messages from your first users |
| Phone notifications | **Yes** on Android and desktop browsers. **iPhone:** only after "Add to Home Screen", iOS 16.4 or later | Nothing; keys are generated automatically (or set `VAPID_PRIVATE_KEY_PEM`) |
| Scale | Fine for the first thousands of users (one server, SQLite, live state in memory) | Run one instance. Past roughly 10,000 active users: Postgres, and Redis for the live hub so you can run several servers |

### Not in the app yet (and said so on the website)
Live cricket scores and predict-the-ball (need a paid, licensed data feed), auction night, Afterglow photo
albums, contact-book friend finding, voice-note transcription on WhatsApp. Recipe cards from reels are built
and switch on with the Claude API key.

### Things that will never work the way people might assume
- Netflix, Prime Video and Hotstar can't be streamed inside another app. Watch parties for those are synced
  links plus a shared countdown (already designed that way).
- Instagram and Snapchat don't give apps your friends list. Friends come from phone contacts, share links and
  WhatsApp groups.
- WhatsApp's rules stop Mindy being a general chatbot on WhatsApp. Keep it a memory and reminders assistant there;
  the open-ended AI lives in the app.
- Real cricket players' names and photos on cards need licences. Start with friend cards and original art.
- Payments are links (UPI, Revolut, PayPal) unless you partner with a payment provider.

## From web app to store apps (later, only if it's worth it)

The web app is the app: no store fees, no review wait, instant updates. When it's proven, wrap the same
`webapp/` for the stores (Capacitor or a Trusted Web Activity for Android) to get store listings and
contact-book access. Google Play charges a one-off $25 and Apple $99 a year, so do it once there's traction.

| Next | What | Rough effort |
|---|---|---|
| 1 | Live cricket data partner, then predict-the-ball and scores in watch parties | 2–3 weeks after the data deal |
| 2 | Photo sharing in chats and Afterglow albums (S3-compatible storage) | 2–3 weeks |
| 3 | Group features on WhatsApp (polls, shared lists) | 2–3 weeks |
| 4 | Store apps wrapping the web app | 1–2 weeks |
| 5 | Postgres + Redis when you pass about 10,000 active people | 1–2 weeks |

## Before you post anything

- [ ] Website live on the domain, HTTPS on, all links work on your phone
- [ ] `/health` says ok, updates sign-up shows in `/admin`
- [ ] App: sign in with your number (code arrives on WhatsApp), invite a friend, chat, play hand cricket, start a watch party
- [ ] App: turn on phone notifications, set "remind me in 2 minutes", it arrives on the phone and on WhatsApp
- [ ] `DEV_CODES` is `0` in production
- [ ] WhatsApp: hi → welcome; a reel → saved; "remind me in 2 minutes" → arrives; photo of a ticket → reminder
- [ ] Instagram (as a tester): share a reel → saved; ask about it → answered; `link` → joined with WhatsApp
- [ ] A reminder set 2 days ahead arrives as the approved template
- [ ] "delete my data" really deletes
- [ ] Privacy policy has your real company details; ICO registration done
