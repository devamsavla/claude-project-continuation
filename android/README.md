# Mindy Helper (Android)

The on-screen helper: a green 🧠 bubble floats on every screen. Press it and say what you want
("Phoenix Mall jaana hai", "video call Riya"). Mindy reads the button names on the current screen, puts a
pulsing ring on the next one and says the step out loud in Hindi or English, until it's done. "I'm stuck"
tells the family and offers a call. With "Let Mindy press the buttons" switched on, it taps for you, never on
PIN/OTP/password fields or pay buttons.

How it works: Android's accessibility service (`HelperService.kt`) reads the visible buttons and boxes as text
(no screenshots), sends them with the goal to the Mindy server (`server/app/helper.py`), which answers with the
one next step: open an app at the right screen (Uber with the drop filled in, Maps, YouTube, WhatsApp), tap,
type, scroll, done, or stuck. The overlay (`Overlay.kt`) draws the ring; text-to-speech reads the step.

## Get the app on a phone (no Play Store needed for the pilot)

1. Push this repo to GitHub. The **android helper apk** workflow builds `app-debug.apk` automatically
   (Actions tab → latest run → Artifacts → `mindy-helper-apk`).
2. Send the APK to the phone (WhatsApp it to yourself), open it, allow "install unknown apps" once.
3. Open Mindy Helper → allow the microphone → switch on Mindy Helper in Accessibility → choose Hindi or English.
4. The 🧠 bubble appears. Press it and talk.

Or build locally: Android Studio → Open the `android/` folder → Run.

## Before the Play Store

- Declare the accessibility use in Play Console (it's an `isAccessibilityTool` for people who need help using
  their phone), add a privacy policy, and record the demo video Google asks for.
- One-off $25 developer fee. Release signing key in GitHub secrets.

## Status

Written without a local Android build (the build tools couldn't be downloaded in the environment it was written in).
The first GitHub Actions run is the compile check: fix anything it reports, then test on a real phone with Uber,
WhatsApp, YouTube and a UPI app. The server side is tested (`server/tests`).
