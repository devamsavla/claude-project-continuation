# Launch checklist

For the technical setup in full (website, backend, WhatsApp, Instagram, costs, what works on day one), see `DEPLOY.md`.

## 1. Domain and website (1 hour)
- Host `website/` on Cloudflare Pages, Netlify or Vercel (drag the folder in; no build step).
- Point `whatsonyourmind.online` and `www` at it (the host shows the DNS records to add at your registrar).
- In `website/index.html`, change `WA_NUMBER` to your WhatsApp Business number (digits only, with country code) and the visible number in the join section.
- Fill the bracketed company details in `privacy.html` and `terms.html` and have them checked by a lawyer.

## 2. Backend and WhatsApp (half a day)
- Follow `backend/README.md`: run the tests locally, deploy to Render with `render.yaml`, point `api.whatsonyourmind.online` at it.
- Create the Meta app, connect the webhook, submit the templates in `backend/TEMPLATES.md`.
- Start Business verification early; it can take days.
- Set the WhatsApp profile from `copy/captions-and-bios.md` and `logo/profile-picture.png`.

## 3. Legal basics (UK)
- Register with the ICO and pay the data protection fee before you process anyone's data.
- Privacy policy and terms live on the site (step 1).
- Keep Mindy task-specific: since 15 January 2026 WhatsApp bars general-purpose AI chatbots.

## 4. Social (1 hour)
- Instagram: profile picture `logo/profile-picture.png`, bio from `copy/`, post `social/instagram-posts/01…09` in order, and the intro reel `social/instagram-reel-mindy-intro.mp4` on launch day.
- LinkedIn / X / YouTube banners in `social/banners/`.
- WhatsApp sticker pack in `stickers/`: 16 WebP stickers (512 × 512, under 100 KB) and a 96 × 96 tray icon. Publish with a sticker-maker app or the WhatsApp sticker SDK.

## 5. The Mindy app
- The real app is `backend/webapp/`, served at app.whatsonyourmind.online. `app-prototype/index.html` is the design tour of the full vision (demo data), handy for investor demos.
- Launch order: WhatsApp first ("just text Mindy"), then point people to the app for friends, plans and games. Send `login` to Mindy for an app code.
- Next: test it with 10 people, then build the real app (React Native or Flutter) against the same backend.
