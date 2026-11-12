<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.

## What Lovable manages

Rules outside this block are the project's own. Change the pieces below in
Lovable, not by hand. With the [Lovable MCP](https://mcp.lovable.dev)
connected, `send_message` asks Lovable to do it; otherwise ask the user to
use the editor.

- **Database.** Do not add or edit `supabase/migrations/` or `drizzle/`.
  Ask Lovable to change the schema.
- **Generated files.** Do not edit a file whose header says it is automatically
  generated.
- **AI gateway.** Keep model calls on Lovable's gateway, and keep
  `LOVABLE_API_KEY` out of browser code.
- **Connectors.** Lovable provides native connectors. `list_connectors` shows
  which are enabled; `add_connector` only returns the dashboard link. When a
  connector is enabled, calls go through the connector gateway and need
  `LOVABLE_API_KEY`. When Lovable does not provide one, users can bring their
  own key and store it in Secrets.
- **Secrets.** Lovable manages them. Do not put secret values in the repo.
<!-- LOVABLE:END -->

## Project rules

- Read `docs/PROGRESS.md` first and update it (plus `roadmap.md`) at the end of every working session. Why: it is the hand-off record other contributors and AI models build on.
- `legacy/claude-launch-kit/` is read-only reference for porting and is excluded from build, lint and tests. Why: it is the original Python/vanilla-JS build, kept only as a behaviour spec.
- The marketing site (/, /whatsapp, /instagram, /app, /privacy, /terms) renders the original whatsonyourmind.online markup from `src/site/pages/*` through `SitePage`, with its own stylesheet per route and behaviour in `src/site/site-init.ts`. Why: keeps the hand-built site pixel-identical to the source; edit copy in those markup files, not in Tailwind components.
- Site stylesheets start with a zero-specificity `revert` block for `.site-root`. Why: the app's global base reset would otherwise change the site's spacing, lists and widths.
- The design tour is a self-contained static file at `public/try/index.html`; link to `/try/index.html`. Why: it is a single-file prototype with demo data and needs no app code.
- Waitlist sign-ups go through the `join_waitlist` database function; the `waitlist` table has no client policies. Why: visitors can join and see their position without being able to read other emails.
- Site settings (WhatsApp number, Instagram handle, where "Open the app" points) live in `src/site/config.ts`. Why: one place to change at launch.
