# Roadmap: bring Mindy over from Claude

- [x] Stage 1: website (home, WhatsApp, Instagram, app, privacy, terms) + design tour at /try/ + working waitlist form
- [ ] Stage 2: the real Mindy web app at /mindy (decided: email + Google sign-in; rules-first parsing with cheapest built-in AI model as fallback)
  - [ ] 2a Database: profiles (name, tz, status, notify, hue), friends, invites, chats, chat members, messages, items (+ search), reminders, lists, occasions, moods, stamps, plans, plan people, push subscriptions, link codes, channel accounts
  - [ ] 2b Sign-in page (email + Google), profile on signup, invite links
  - [ ] 2c Port app.js / mindy.js / app.css; swap its API calls to server functions/routes with the same JSON shapes as the original api.py
  - [ ] 2d Port brain.py rules (dates, reminders, lists, birthdays, plans, money) to TypeScript; AI fallback only when rules fail
  - [ ] 2e Live updates (chat, status, plans) via realtime; hand cricket + Last Card state stored in the database
  - [ ] 2f Reminders delivery on a schedule + phone notifications (Web Push)
  - [ ] 2g Admin numbers page, export and delete my data; point "Open the app" (src/site/config.ts) at /mindy
- [ ] Stage 3: Mindy on WhatsApp and Instagram (needs Meta app credentials from the user)
- [ ] Before launch: real WhatsApp number, Instagram handle (src/site/config.ts) and company details in privacy/terms
