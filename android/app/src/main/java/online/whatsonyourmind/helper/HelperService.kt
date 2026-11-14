package online.whatsonyourmind.helper

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Mindy Helper. A small Mindy bubble floats on every screen. Press it, say what you want ("Phoenix Mall jaana hai",
 * "video call Riya"), and Mindy reads the buttons on the current screen, puts a pulsing ring on the next one to
 * press and says it out loud. When the screen changes, it works out the next step, until it's done.
 * If they get stuck, one tap tells the family. It never reads or types PINs/OTPs and never presses pay buttons.
 */
class HelperService : AccessibilityService(), TextToSpeech.OnInitListener {
    private lateinit var wm: WindowManager
    private lateinit var prefs: Prefs
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var recognizer: SpeechRecognizer? = null

    private var bubble: TextView? = null
    private var pointer: PointerView? = null
    private var card: LinearLayout? = null
    private var cardText: TextView? = null

    private var goal: String? = null
    private val history = ArrayList<String>()
    private var items: List<Item> = emptyList()
    private var inFlight = false
    private var lastSay = ""
    private var steps = 0
    private val nextRunnable = Runnable { requestNext() }

    private val dp get() = resources.displayMetrics.density

    override fun onServiceConnected() {
        super.onServiceConnected()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        prefs = Prefs(this)
        tts = TextToSpeech(this, this)
        showBubble()
        io.execute { Api.ensureToken(this) }
    }

    override fun onInit(status: Int) {
        ttsReady = status == TextToSpeech.SUCCESS
        if (ttsReady) {
            tts?.setLanguage(if (prefs.lang.startsWith("hi")) Locale("hi", "IN") else Locale("en", "IN"))
            tts?.setSpeechRate(0.9f)
        }
    }

    // ------------------------------------------------------------------ overlays
    private fun overlayParams(w: Int, h: Int, touchable: Boolean): WindowManager.LayoutParams {
        var flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        if (!touchable) flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        return WindowManager.LayoutParams(w, h, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY, flags, PixelFormat.TRANSLUCENT)
    }

    private fun showBubble() {
        val b = TextView(this).apply {
            text = "🧠"
            textSize = 26f
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.rgb(37, 211, 102))
                setStroke((3 * dp).toInt(), Color.BLACK)
            }
            contentDescription = "Mindy: press and say what you want to do"
        }
        val size = (64 * dp).toInt()
        val lp = overlayParams(size, size, true).apply {
            gravity = Gravity.TOP or Gravity.END
            x = (8 * dp).toInt()
            y = (220 * dp).toInt()
        }
        // tap to talk; drag to move
        var downY = 0f
        var startY = 0
        var moved = false
        b.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { downY = e.rawY; startY = lp.y; moved = false; true }
                MotionEvent.ACTION_MOVE -> {
                    val dy = (e.rawY - downY).toInt()
                    if (kotlin.math.abs(dy) > 12 * dp) moved = true
                    if (moved) { lp.y = startY + dy; wm.updateViewLayout(v, lp) }
                    true
                }
                MotionEvent.ACTION_UP -> { if (!moved) onBubbleTap(); true }
                else -> false
            }
        }
        wm.addView(b, lp)
        bubble = b
    }

    private fun ensurePointer(): PointerView {
        pointer?.let { return it }
        val p = PointerView(this)
        val lp = overlayParams(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT, false).apply {
            gravity = Gravity.TOP or Gravity.START
            flags = flags or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
        }
        wm.addView(p, lp)
        pointer = p
        return p
    }

    private fun button(label: String, bg: Int, fg: Int, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 17f
        setTextColor(fg)
        background = GradientDrawable().apply { cornerRadius = 40 * dp; setColor(bg) }
        setPadding((14 * dp).toInt(), (6 * dp).toInt(), (14 * dp).toInt(), (6 * dp).toInt())
        setOnClickListener { onClick() }
    }

    /** The card at the bottom: what to do now, plus Repeat, I'm stuck and Stop. */
    private fun showCard(message: String, choices: List<Pair<String, () -> Unit>>? = null) {
        val hi = prefs.lang.startsWith("hi")
        if (card == null) {
            val c = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding((18 * dp).toInt(), (16 * dp).toInt(), (18 * dp).toInt(), (16 * dp).toInt())
                background = GradientDrawable().apply {
                    cornerRadius = 26 * dp
                    setColor(Color.rgb(245, 243, 238))
                    setStroke((3 * dp).toInt(), Color.BLACK)
                }
            }
            val t = TextView(this).apply { textSize = 21f; setTextColor(Color.BLACK) }
            c.addView(t)
            val lp = overlayParams(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT, true).apply {
                gravity = Gravity.BOTTOM
                y = (24 * dp).toInt()
                horizontalMargin = 0.03f
            }
            wm.addView(c, lp)
            card = c
            cardText = t
        }
        cardText?.text = message
        val c = card ?: return
        while (c.childCount > 1) c.removeViewAt(1)
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, (12 * dp).toInt(), 0, 0) }
        val list = choices ?: listOf(
            (if (hi) "🔊 फिर से" else "🔊 Again") to { speak(lastSay) },
            (if (hi) "📞 मदद" else "📞 I'm stuck") to { stuck() },
            (if (hi) "✕ बंद" else "✕ Stop") to { endSession() }
        )
        for ((label, action) in list) {
            val bt = button(label, Color.BLACK, Color.WHITE, action)
            val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            lp.marginEnd = (8 * dp).toInt()
            row.addView(bt, lp)
        }
        c.addView(row)
    }

    private fun hideCard() {
        card?.let { runCatching { wm.removeView(it) } }
        card = null
        cardText = null
    }

    private fun clearPointer() = pointer?.point(null)

    private fun speak(text: String) {
        if (text.isBlank()) return
        lastSay = text
        if (ttsReady) tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "mindy")
    }

    // ------------------------------------------------------------------ asking what they want
    private fun onBubbleTap() {
        if (goal != null) { showCard(lastSay); speak(lastSay); return }
        val hi = prefs.lang.startsWith("hi")
        val ask = if (hi) "बोलिए, क्या करना है?" else "What do you want to do?"
        showCard(ask, listOf(
            (if (hi) "🎙️ बोलें" else "🎙️ Speak") to { listen() },
            (if (hi) "🚕 कैब" else "🚕 Cab") to { startSession(if (hi) "कैब बुक करनी है" else "book a cab") },
            (if (hi) "📹 वीडियो कॉल" else "📹 Video call") to { startSession(if (hi) "व्हाट्सऐप पर वीडियो कॉल करनी है" else "make a WhatsApp video call") },
            "✕" to { hideCard() }
        ))
        speak(ask)
        listen()
    }

    private fun listen() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            showCard(if (prefs.lang.startsWith("hi")) "इस फ़ोन पर बोलकर बताना काम नहीं कर रहा। ऊपर के बटन चुनें।" else "Speaking isn't available on this phone. Pick a button instead.")
            return
        }
        recognizer?.destroy()
        val r = SpeechRecognizer.createSpeechRecognizer(this)
        recognizer = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onResults(results: Bundle?) {
                val said = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (!said.isNullOrBlank()) startSession(said)
            }
            override fun onError(error: Int) {
                showCard(if (prefs.lang.startsWith("hi")) "सुनाई नहीं दिया। 🧠 दबाकर फिर बोलिए।" else "I didn't catch that. Press 🧠 and try again.")
            }
            override fun onReadyForSpeech(params: Bundle?) { cardText?.text = if (prefs.lang.startsWith("hi")) "🎙️ सुन रहा हूँ…" else "🎙️ Listening…" }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onPartialResults(partialResults: Bundle?) {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, if (prefs.lang.startsWith("hi")) "hi-IN" else "en-IN")
        }
        // give the spoken question a moment to finish before listening
        main.postDelayed({ runCatching { r.startListening(i) } }, 1400)
    }

    // ------------------------------------------------------------------ the guiding loop
    private fun startSession(said: String) {
        goal = said
        history.clear()
        steps = 0
        showCard("“$said”\n" + if (prefs.lang.startsWith("hi")) "देख रहा हूँ…" else "Looking…")
        requestNext()
    }

    private fun endSession() {
        goal = null
        main.removeCallbacks(nextRunnable)
        clearPointer()
        hideCard()
        tts?.stop()
    }

    private fun scheduleNext(delayMs: Long) {
        main.removeCallbacks(nextRunnable)
        main.postDelayed(nextRunnable, delayMs)
    }

    private fun requestNext() {
        val g = goal ?: return
        if (inFlight) { scheduleNext(800); return }
        if (steps >= 30) { showCard(if (prefs.lang.startsWith("hi")) "बहुत कदम हो गए। परिवार से मदद लें?" else "That's a lot of steps. Ask family for help?"); return }
        val root = rootInActiveWindow
        val pkg = root?.packageName?.toString() ?: ""
        if (pkg == packageName) { scheduleNext(1200); return }
        val (nodes, list) = ScreenReader.read(root)
        items = list
        if (ScreenReader.sensitive(list)) {
            clearPointer()
            val msg = if (prefs.lang.startsWith("hi")) "यह आपका PIN या OTP है। इसे सिर्फ़ आप भरें, मैं नहीं देख रहा।" else "This is your PIN or OTP. Only you should type it. I'm not looking."
            showCard(msg); speak(msg)
            scheduleNext(6000)
            return
        }
        inFlight = true
        steps++
        val body = JSONObject().put("goal", g).put("pkg", pkg).put("nodes", nodes).put("lang", prefs.lang)
            .put("history", JSONArray(history.takeLast(8)))
        io.execute {
            val r = Api.post(this, "/api/helper/next", body)
            main.post {
                inFlight = false
                if (goal == null) return@post
                if (r == null) {
                    val msg = if (prefs.lang.startsWith("hi")) "इंटरनेट नहीं मिल रहा। थोड़ी देर में फिर कोशिश करें।" else "I can't reach the internet. Try again in a moment."
                    showCard(msg); speak(msg); return@post
                }
                act(r)
            }
        }
    }

    private fun act(r: JSONObject) {
        val say = r.optString("say", "")
        val action = r.optString("action", "tap")
        if (say.isNotBlank()) history.add(say)
        when (action) {
            "open" -> {
                clearPointer()
                showCard(say); speak(say)
                runCatching {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(r.optString("url"))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                scheduleNext(3500)
            }
            "done" -> {
                clearPointer()
                val msg = say.ifBlank { if (prefs.lang.startsWith("hi")) "हो गया! 🎉" else "All done! 🎉" }
                showCard(msg); speak(msg)
                main.postDelayed({ endSession() }, 5000)
            }
            "stuck" -> { clearPointer(); showCard(say); speak(say) }
            "private" -> { clearPointer(); showCard(say); speak(say); scheduleNext(6000) }
            "wait" -> { showCard(say); scheduleNext(2500) }
            else -> {
                val target = items.firstOrNull { it.index == r.optInt("target", -1) }
                ensurePointer().point(target?.rect)
                showCard(say); speak(say)
                if (target != null && prefs.doIt && !r.optBoolean("user_only", false) && !target.password) doIt(action, target, r.optString("text"))
                // otherwise wait for them to tap: the screen change event triggers the next step
            }
        }
    }

    /** "Do it for me" mode: Mindy presses or types itself, never on PIN/OTP fields or pay buttons. */
    private fun doIt(action: String, target: Item, text: String) {
        main.postDelayed({
            when (action) {
                "type" -> if (text.isNotBlank()) {
                    val args = Bundle()
                    args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
                    target.node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
                }
                "scroll" -> target.node.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                else -> (ScreenReader.clickable(target.node) ?: target.node).performAction(AccessibilityNodeInfo.ACTION_CLICK)
            }
            scheduleNext(1500)
        }, 2200)
    }

    private fun stuck() {
        val g = goal ?: "phone help"
        val hi = prefs.lang.startsWith("hi")
        showCard(if (hi) "परिवार को बता रहा हूँ…" else "Telling your family…")
        io.execute {
            val r = Api.post(this, "/api/helper/stuck", JSONObject().put("goal", g))
            main.post {
                val phone = prefs.familyPhone.ifBlank { r?.optString("call", "") ?: "" }.filter { it.isDigit() }
                val msg = if (hi) "परिवार को बता दिया। उन्हें कॉल करें?" else "Your family knows. Call them now?"
                showCard(msg, listOf(
                    (if (hi) "📞 कॉल करें" else "📞 Call") to {
                        if (phone.isNotEmpty()) runCatching {
                            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/$phone")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                        }
                        endSession()
                    },
                    "✕" to { endSession() }
                ))
                speak(msg)
            }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (goal == null || event == null) return
        if (event.packageName?.toString() == packageName) return
        when (event.eventType) {
            AccessibilityEvent.TYPE_VIEW_CLICKED, AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> { clearPointer(); scheduleNext(1300) }
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> scheduleNext(2500)
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> if (!inFlight && items.isEmpty()) scheduleNext(2000)
        }
    }

    override fun onInterrupt() { tts?.stop() }

    override fun onDestroy() {
        endSession()
        bubble?.let { runCatching { wm.removeView(it) } }
        pointer?.let { runCatching { wm.removeView(it) } }
        recognizer?.destroy()
        tts?.shutdown()
        io.shutdown()
        super.onDestroy()
    }
}
