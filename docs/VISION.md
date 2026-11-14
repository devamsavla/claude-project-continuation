# Vision: Mindy, one tech friend for everything

Meta AI is a chatbot for one person. Mindy is the friend who **does it with you**: it remembers everything,
turns what you save into things that happen, looks after your family, keeps your money straight, protects you
from scams and helps with any app on your phone. It works with the apps people already use and doesn't replace
them. People pay for the convenience.

## Why people come back every day

| Hook | What it does | Status |
|---|---|---|
| Saves → real life | People save dozens of reels and never use them. Mindy works out what each save is (recipe, place, workout, study, product, trip, event) and offers one-tap actions: shopping list + cook reminder, plan with friends, weekly workout, revision quiz. Friend matches: "You and Rohan both saved this vada pav spot → plan it". Weekly Saved→Done score and streak. | **Built** (`server/app/hooks.py`) |
| Family care | A son abroad sets "BP tablet, every day 9am" for his mum. She gets it on WhatsApp with "I took it". If she doesn't tap within 45 min, the family is alerted. Simple mode gives parents big buttons and voice. | **Built** (`server/app/care.py`) |
| Khata | "Ramesh owes me 500", "paid Sunil 300". Running balance per person; "remind Ramesh" makes a ready WhatsApp message with a tap-to-pay UPI link. | **Built** (`server/app/skills.py`) |
| Scam shield | Forward any message, link or number: pattern checks, look-alike bank sites, `.apk` links, short links, community reports (our own growing spam database), optional Google Safe Browsing. | **Built** |
| Do it for me | "Book an uber to Phoenix Mall" → one tap opens Uber with the drop filled in. Directions, calls, WhatsApp chats, UPI payments the same way (deep links, no partnership needed). | **Built** |
| Screenshot help | Send a screenshot from any app + a question → the screenshot comes back with a circle where to tap and the step in simple words (spoken in the app). Privacy check-up reads the iPhone App Privacy Report / Android Privacy dashboard. | **Built** (needs `LLM_API_KEY`) |
| Study help | Study saves become quizzes; homework photo → method and hints, not just the answer (app and Telegram only). | **Built** (needs `LLM_API_KEY`) |
| File tools | Send a video with "mp3" or "compress": converted and sent back (ffmpeg). Photos compressed too. Only files people send; no downloading other people's content. | **Built** |
| Plans, chats, games, watch parties | Who's free now, chats with @mindy, hand cricket, Last Card, synced YouTube, countdown for Netflix. | **Built** |

## Channels

| Channel | Role | Rules |
|---|---|---|
| WhatsApp | First touch: no install. Memory, reminders, family, khata, scam checks, do-it links, file tools. | **Task-specific only** (WhatsApp bans general AI chatbots since 15 Jan 2026). Reminders after 24 h need paid templates. |
| Telegram | The open, free channel: everything above **plus open chat**, free reminders, forwarded channel posts saved. | Bot sees only chats it's in; no scraping. |
| Instagram | Share reels to Mindy. | 24-hour window; reminders go elsewhere. |
| Web app (PWA) | Friends, plans, games, watch parties, Mind, family, khata, simple mode. | Phone notifications via Web Push (iPhone: after Add to Home Screen). |

Reminders go out on the cheapest channel that reaches the person: app/push (free) → WhatsApp inside 24 h (free)
→ Telegram (free) → WhatsApp template (paid).

## Layer 2: Mindy Helper for Android (native, ~4 weeks)

- **Pointer on top of any app** (like on-screen Maps directions): an `AccessibilityService` reads the screen's
  UI tree, the cheap model picks the next element for the goal ("book an Uber to Lilavati Hospital"), and a
  `TYPE_ACCESSIBILITY_OVERLAY` window draws a pulsing ring there and speaks the step (Hindi/English).
- **Do-it mode**: with consent, Mindy performs the taps itself (`performAction`) while the user watches.
- **Caller ID and spam blocking**: `CallScreeningService` + the "Caller ID & spam app" role, fed by our spam
  database and verified-business numbers. No contact-book uploading.
- **Privacy scan**: list installed apps and permissions; flag SMS access, accessibility, overlay, device admin,
  sideloaded apps, and unused apps still holding location/mic/camera; one tap opens the right settings page.
- Play policy: accessibility API is allowed for tools that help users with disabilities and older users; declare
  it, explain it in the listing, record a demo video. `QUERY_ALL_PACKAGES` is allowed for security/privacy apps.
- Stack: Kotlin module inside an Expo (React Native) app, or a small native Kotlin app that opens the web app for everything else.

## Layer 3: Mindy Helper for iPhone

- Apple forbids drawing over or reading other apps. Closest legal version:
  - **Live screen guidance**: ReplayKit broadcast upload extension streams the screen (user taps "Help me");
    the server samples frames to the vision model; guidance appears in a **Picture-in-Picture** window that floats
    over the other app, plus a **Live Activity** on the lock screen/Dynamic Island, plus voice.
  - **Family live help**: a family member watches the stream and talks them through it.
  - **Spam labels** for incoming calls via a CallKit Call Directory extension (same mechanism Truecaller uses on iPhone).

## Connectors (later)

Google Calendar, Gmail (bills and tickets → reminders), Google Contacts (find friends), Uber/Ola (ride status),
banks via Account Aggregator (balances → khata), Razorpay/UPI collect for business reminders.

## Business

- Free: memory, in-app reminders, scam checks, khata, family basics.
- **Plus** (₹99/mo): unlimited WhatsApp reminders, voice notes, bill photos, group reminders, more AI.
- **Care** (₹199/mo): Plus for a parent, missed-dose alerts, up to 5 family members.
- Business: verified numbers ("✅ Verified by Mindy"), reminder service for clinics/salons/tutors, pharmacy refills.
