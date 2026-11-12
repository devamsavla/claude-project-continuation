# Original Claude launch kit (reference only)

This folder is the founder's original build from the Claude desktop app. **It is not built, served or tested
by this project.** It is kept so Stage 2 and Stage 3 can be ported faithfully.

| Path | What it is | Port status |
| --- | --- | --- |
| `backend/app/db.py` | SQLite schema (users, messages, items, reminders, lists, occasions, accounts, link codes…) | Stage 2a — to port to Lovable Cloud tables |
| `backend/app/api.py` | ~45 JSON endpoints for the web app (friends, chats, plans, saves, reminders, passport, push…) | Stage 2c — to port to server functions, same JSON shapes |
| `backend/app/auth.py` | WhatsApp-code sign-in | Replaced: email + Google sign-in (decided) |
| `backend/app/brain.py` | Message parsing (dates, reminders, lists, birthdays, plans, money) + Claude calls | Stage 2d — rules to TypeScript; AI fallback on built-in model |
| `backend/app/realtime.py` | WebSocket chat / presence | Stage 2e — to Lovable Cloud realtime |
| `backend/app/games.py` | Hand cricket + Last Card | Stage 2e — state in the database |
| `backend/app/main.py` | App startup, reminder scheduler, admin endpoints | Stage 2f/2g — scheduled job + admin page |
| `backend/app/handlers.py`, `whatsapp.py`, `instagram.py` | WhatsApp / Instagram webhook bot | Stage 3 — needs Meta credentials |
| `backend/webapp/` | Vanilla-JS Mindy web app (`app.js`, `mindy.js`, `app.css`) | Stage 2c — to port to React under `/mindy` |
| `backend/tests/` | 24 pytest tests | Use as behaviour spec when porting |
| `backend/TEMPLATES.md` | WhatsApp message templates to get approved by Meta | Stage 3 |
| `backend/.env.example` | Example settings (placeholders only, no real secrets) | Secrets go in Lovable Cloud, never in the repo |
| `DEPLOY.md`, `LAUNCH.md`, `KIT-README.md` | The kit's own deploy and launch notes | Partly superseded (hosting is now Lovable) |
| `copy/` | Instagram bio/captions, notification copy in three personalities | Reuse in Stage 2/3 |
| `app-tour-brief.md` | Text of the design tour's intro | Reference |

Already migrated (not duplicated here): the website (`src/site/`), the design tour (`public/try/`), stickers and screenshots (`public/`).
Brand art (logos, social posts, reel) stayed in the founder's original ZIP.
