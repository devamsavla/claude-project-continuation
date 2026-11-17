package online.whatsonyourmind.helper

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.os.Build
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * Setup, done once (usually by a son or daughter): allow the microphone, switch on the Mindy Helper
 * accessibility service, pick the language, add a family WhatsApp number. After that the Mindy bubble
 * appears on every screen.
 */
class MainActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var status: TextView
    private val dp get() = resources.displayMetrics.density

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((22 * dp).toInt(), (40 * dp).toInt(), (22 * dp).toInt(), (40 * dp).toInt())
            setBackgroundColor(Color.BLACK)
        }
        fun label(t: String, size: Float, color: Int = Color.WHITE, bold: Boolean = false) = TextView(this).apply {
            text = t
            textSize = size
            setTextColor(color)
            if (bold) typeface = Typeface.DEFAULT_BOLD
            setPadding(0, (8 * dp).toInt(), 0, (8 * dp).toInt())
        }
        fun big(t: String, bg: Int, fg: Int, onClick: () -> Unit) = Button(this).apply {
            text = t
            isAllCaps = false
            textSize = 19f
            setTextColor(fg)
            background = GradientDrawable().apply { cornerRadius = 40 * dp; setColor(bg) }
            setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (60 * dp).toInt()).apply { topMargin = (12 * dp).toInt() }
        }
        fun field(hint: String, value: String, type: Int) = EditText(this).apply {
            this.hint = hint
            setText(value)
            inputType = type
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            textSize = 18f
        }

        col.addView(label("🧠 Mindy Helper", 34f, bold = true))
        col.addView(label("Press the Mindy bubble on any screen and say what you want to do. Mindy points to the next button and says it out loud, step by step.", 17f, Color.LTGRAY))
        status = label("", 17f, Color.rgb(37, 211, 102), bold = true)
        col.addView(status)

        col.addView(big("1. Allow the microphone", Color.rgb(245, 243, 238), Color.BLACK) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 7)
        })
        col.addView(big("2. Switch on Mindy Helper", Color.rgb(37, 211, 102), Color.BLACK) {
            Toast.makeText(this, "Find “Mindy Helper” in the list and switch it on", Toast.LENGTH_LONG).show()
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })

        col.addView(label("Language", 15f, Color.GRAY))
        val langRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val hindi = Button(this).apply { text = "हिंदी"; isAllCaps = false }
        val english = Button(this).apply { text = "English"; isAllCaps = false }
        fun paintLang() {
            hindi.alpha = if (prefs.lang.startsWith("hi")) 1f else 0.4f
            english.alpha = if (prefs.lang.startsWith("hi")) 0.4f else 1f
        }
        hindi.setOnClickListener { prefs.lang = "hi"; paintLang() }
        english.setOnClickListener { prefs.lang = "en"; paintLang() }
        paintLang()
        langRow.addView(hindi)
        langRow.addView(english)
        col.addView(langRow)

        val name = field("Your name (so family knows it's you)", prefs.name, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_WORDS)
        val family = field("Family WhatsApp number, e.g. +44 7700 900111", prefs.familyPhone, InputType.TYPE_CLASS_PHONE)
        val doit = CheckBox(this).apply {
            text = "Let Mindy press the buttons for me (never PINs or payments)"
            setTextColor(Color.WHITE)
            isChecked = prefs.doIt
        }
        val familyCode = field("Family code from Mindy (optional)", "", InputType.TYPE_CLASS_NUMBER)
        val server = field("Server", prefs.server, InputType.TYPE_TEXT_VARIATION_URI)
        col.addView(name)
        col.addView(family)
        col.addView(familyCode)
        col.addView(doit)
        col.addView(big("Save", Color.rgb(245, 243, 238), Color.BLACK) {
            prefs.name = name.text.toString().trim()
            prefs.familyPhone = family.text.toString().trim()
            prefs.doIt = doit.isChecked
            val s = server.text.toString().trim()
            if (s.startsWith("http")) prefs.server = s
            val code = familyCode.text.toString().trim()
            Thread {
                Api.ensureToken(this)
                if (prefs.name.isNotEmpty()) Api.post(this, "/api/me/name", org.json.JSONObject().put("name", prefs.name))
                val joined = if (code.length == 6) Api.post(this, "/api/family/join", org.json.JSONObject().put("code", code)) != null else null
                runOnUiThread {
                    Toast.makeText(this, when (joined) { true -> "Saved and linked with family ✅"; false -> "Saved. That family code didn't work."; null -> "Saved ✅" }, Toast.LENGTH_LONG).show()
                }
            }.start()
        })
        col.addView(label("Caller ID", 15f, Color.GRAY))
        col.addView(big("3. Turn on scam caller warnings", Color.rgb(255, 226, 154), Color.BLACK) {
            if (Build.VERSION.SDK_INT >= 29) {
                val rm = getSystemService(android.app.role.RoleManager::class.java)
                if (rm.isRoleAvailable(android.app.role.RoleManager.ROLE_CALL_SCREENING) && !rm.isRoleHeld(android.app.role.RoleManager.ROLE_CALL_SCREENING))
                    startActivityForResult(rm.createRequestRoleIntent(android.app.role.RoleManager.ROLE_CALL_SCREENING), 7)
                else Toast.makeText(this, "Caller ID is on ✅", Toast.LENGTH_SHORT).show()
                if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 8)
            } else Toast.makeText(this, "Needs Android 10 or newer", Toast.LENGTH_LONG).show()
        })
        val block = android.widget.CheckBox(this).apply { text = "Silence calls reported 5+ times"; setTextColor(Color.WHITE); isChecked = prefs.blockScams
            setOnCheckedChangeListener { _, v -> prefs.blockScams = v } }
        col.addView(block)
        col.addView(label("Advanced", 13f, Color.DKGRAY))
        col.addView(server)
        val gw = field("Gateway secret (Mindy team phone only)", prefs.gatewaySecret, InputType.TYPE_CLASS_TEXT)
        col.addView(gw)
        col.addView(big("Gateway mode on / off", Color.DKGRAY, Color.WHITE) {
            prefs.gatewaySecret = gw.text.toString().trim()
            val i = Intent(this, GatewayService::class.java)
            if (prefs.gatewaySecret.isEmpty()) { stopService(i); Toast.makeText(this, "Gateway off", Toast.LENGTH_SHORT).show() }
            else {
                requestPermissions(arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.SEND_SMS, Manifest.permission.READ_PHONE_STATE, Manifest.permission.READ_CALL_LOG), 9)
                if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
                Toast.makeText(this, "Gateway on", Toast.LENGTH_SHORT).show()
            }
        })
        col.addView(label("Mindy never reads or types your PIN, OTP or passwords, and never presses Pay for you. It only reads the button names on the screen you're on, while you're asking for help.", 13f, Color.GRAY))

        setContentView(ScrollView(this).apply { setBackgroundColor(Color.BLACK); addView(col) })
    }

    override fun onResume() {
        super.onResume()
        val on = (Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "").contains(packageName)
        val mic = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        status.text = when {
            on && mic -> "✅ Ready. Look for the green 🧠 bubble on any screen."
            on -> "Almost: allow the microphone so you can speak to Mindy."
            else -> "Not switched on yet. Do steps 1 and 2."
        }
    }
}
