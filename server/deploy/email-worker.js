// Cloudflare Email Worker: forwards emails sent to <key>@in.whatsonyourmind.online to Mindy.
// Setup (free): Cloudflare dashboard → your domain → Email → Email Routing → enable, then
// Routing rules → Catch-all → Action "Send to a Worker" → this worker.
// Worker settings → Variables: MINDY_URL = https://api.whatsonyourmind.online/webhook/email, MINDY_SECRET = EMAIL_WEBHOOK_SECRET.
// Deploy with wrangler (npm i postal-mime first) or paste into the dashboard editor with "postal-mime" added.
import PostalMime from "postal-mime";

export default {
  async email(message, env) {
    const mail = await PostalMime.parse(message.raw);
    const text = (mail.text || (mail.html || "").replace(/<[^>]+>/g, " ")).slice(0, 6000);
    const res = await fetch(env.MINDY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Mindy-Secret": env.MINDY_SECRET },
      body: JSON.stringify({ to: message.to, from: message.from, subject: mail.subject || "", text }),
    });
    if (!res.ok) message.setReject("Mindy couldn't take this email right now.");
  },
};
