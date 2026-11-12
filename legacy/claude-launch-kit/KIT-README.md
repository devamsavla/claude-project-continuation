# whatsonyourmind launch kit

Everything to launch Mindy: brand, social, website, the working Mindy web app and the backend for WhatsApp and Instagram.
Start with `DEPLOY.md` (how to put it all live, costs, and what works on day one), then `LAUNCH.md`.

| Folder | What's inside |
|---|---|
| `logo/` | Logos (light, dark, transparent, stacked), wordmarks, app icons for whatsonyourmind and the Mindy app, favicon, profile picture, mood and prop sheets; `svg/` has Mindy in 9 moods as scalable SVG |
| `social/instagram-posts/` | 12 launch posts, 1080 × 1350, to post in order |
| `social/instagram-stories/` | 3 stories, 1080 × 1920 |
| `social/instagram-reel-mindy-intro.mp4` | 12.5-second vertical intro reel, 1080 × 1920 |
| `social/banners/` | LinkedIn, X, YouTube banners and the website's share image |
| `stickers/` | WhatsApp sticker pack: 16 Mindy stickers (WebP, 512 × 512) and a tray icon |
| `copy/` | Instagram bio and captions, WhatsApp profile text, posting plan, notification copy in three personalities |
| `website/` | whatsonyourmind.online: Home (WhatsApp first), WhatsApp, Instagram, The app (real screenshots), app tour, privacy, terms. Static files, no build step |
| `app-prototype/` | The design tour (demo data, also at website/try/): the full vision (one HTML file): Now, Chats, the thought bubble, Plans (watch parties, trips, split, play), Mind (ready, tracking, remember, study, money), Me (profile, passport, connections) |
| `backend/` | One server for Mindy on WhatsApp, Instagram **and the real Mindy web app** (`backend/webapp/`): sign in with WhatsApp, friends, live chats with @mindy, plans, watch parties, hand cricket, Last Card, reminders, saves, charts, passport, phone notifications. FastAPI + Claude, 24 tests, Docker and Render deploy |
| `screens/` | Screenshots of the real web app, for posts and the store listing later |

Fonts used everywhere: Bricolage Grotesque, Figtree, Instrument Serif and JetBrains Mono (all free on Google Fonts).
