# WhatsApp message templates to submit

Submit these in WhatsApp Manager > Message templates. Use category **Utility** (cheaper than Marketing,
and these are triggered by something the user asked for). Language: English (UK), code `en_GB`.

| Name | Category | Body | Used for |
|---|---|---|---|
| `mindy_reminder` | Utility | `⏰ Reminder: {{1}}` (sample: `call mum`) | Reminders and occasion nudges when the user hasn't messaged in 24 hours |
| `mindy_weekly` | Utility | `Your week with Mindy: {{1}} things saved, {{2}} reminders coming up. Reply *upcoming* to see them.` | Optional Sunday summary |
| `mindy_care` | Utility | `💊 Time for: {{1}}. Tap “I took it” when done, or reply *took*.` with quick-reply buttons `I took it` and `In 15 min` | Family care reminders outside the 24-hour window |
| `mindy_care_alert` | Utility | `⚠️ {{1}} hasn't confirmed {{2}} yet. You might want to give them a call.` | Missed-dose alert to family |
| `mindy_sos` | Utility | `🆘 {{1}} pressed SOS. Their location: {{2}}` | SOS button: alerts family with a map link |
| `mindy_login_code` | **Authentication** | Meta's fixed authentication text: `{{1}} is your verification code.` with a **Copy code** button. Add the security recommendation and a 10-minute expiry. | Sign-in codes for the Mindy app when the user hasn't messaged Mindy in 24 hours |
| `mindy_welcome_back` | Utility | `Your saved items are safe. Reply *help* any time to pick up where you left off.` | After 30 days quiet (only if the user opted in) |

Inside the 24-hour customer service window (after the user's last message) Mindy replies freely with
text and buttons at no charge; templates are only for messages Mindy starts.

### About the sign-in template
Authentication templates have fixed wording set by Meta; you only pick the button (choose **Copy code**) and the
expiry. They are priced as authentication messages (cheaper than marketing in most countries). Inside the 24-hour
window, Mindy sends the code as a normal text instead, which is free. People can also send **login** to Mindy and get
a code back with no template at all.
