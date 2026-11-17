package online.whatsonyourmind.helper

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Telephony
import android.telephony.SmsManager
import android.telephony.TelephonyManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Gateway mode: turns a spare Android phone with a cheap SIM into Mindy's missed-call and SMS line for basic phones.
 *  Missed call -> server -> a menu by SMS. Incoming SMS -> server -> Mindy's replies are sent back as SMS from this phone.
 *  Only for the phone the Mindy team runs; it needs the gateway secret. */
object GatewayApi {
    fun send(ctx: Context, path: String, body: JSONObject? = null): JSONObject? = try {
        val p = Prefs(ctx)
        val c = URL(p.server + path).openConnection() as HttpURLConnection
        c.requestMethod = if (body == null) "GET" else "POST"
        c.connectTimeout = 8000; c.readTimeout = 15000
        c.setRequestProperty("X-Gateway-Secret", p.gatewaySecret)
        c.setRequestProperty("Content-Type", "application/json")
        if (body != null) { c.doOutput = true; c.outputStream.use { it.write(body.toString().toByteArray()) } }
        val t = if (c.responseCode < 400) c.inputStream.bufferedReader().use { it.readText() } else null
        c.disconnect()
        t?.let { JSONObject(it) }
    } catch (e: Exception) { null }
}

class SmsIn : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (Prefs(ctx).gatewaySecret.isEmpty() || intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val from = parts.firstOrNull()?.originatingAddress ?: return
        val body = parts.joinToString("") { it.messageBody ?: "" }
        val pending = goAsync()
        Thread { GatewayApi.send(ctx, "/api/gateway/sms", JSONObject().put("from", from).put("body", body)); pending.finish() }.start()
    }
}

class MissedCall : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (Prefs(ctx).gatewaySecret.isEmpty()) return
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        @Suppress("DEPRECATION") val num = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
        val sp = ctx.getSharedPreferences("gw", Context.MODE_PRIVATE)
        when (state) {
            TelephonyManager.EXTRA_STATE_RINGING -> if (!num.isNullOrEmpty()) sp.edit().putString("ringing", num).putBoolean("answered", false).apply()
            TelephonyManager.EXTRA_STATE_OFFHOOK -> sp.edit().putBoolean("answered", true).apply()
            TelephonyManager.EXTRA_STATE_IDLE -> {
                val n = sp.getString("ringing", null)
                if (n != null && !sp.getBoolean("answered", false)) {
                    val pending = goAsync()
                    Thread { GatewayApi.send(ctx, "/api/gateway/missed", JSONObject().put("from", n)); pending.finish() }.start()
                }
                sp.edit().remove("ringing").apply()
            }
        }
    }
}

/** Keeps sending Mindy's queued SMS replies while gateway mode is on. */
class GatewayService : Service() {
    private val h = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            Thread {
                val out = GatewayApi.send(this@GatewayService, "/api/gateway/outbox")?.optJSONArray("messages")
                val sms = if (Build.VERSION.SDK_INT >= 31) getSystemService(SmsManager::class.java) else @Suppress("DEPRECATION") SmsManager.getDefault()
                for (i in 0 until (out?.length() ?: 0)) {
                    val m = out!!.getJSONObject(i)
                    try { sms.sendMultipartTextMessage(m.getString("to_number").let { if (it.startsWith("+")) it else "+$it" }, null, sms.divideMessage(m.getString("body")), null, null) } catch (_: Exception) {}
                }
            }.start()
            h.postDelayed(this, 15000)
        }
    }

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("gw", "Mindy gateway", NotificationManager.IMPORTANCE_LOW))
        val n = (if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "gw") else Notification.Builder(this))
            .setSmallIcon(android.R.drawable.stat_notify_chat).setContentTitle("Mindy gateway is on").setContentText("Answering missed calls and SMS").build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(7, n, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(7, n)
        h.post(tick)
    }

    override fun onDestroy() { h.removeCallbacks(tick); super.onDestroy() }
    override fun onBind(i: Intent?): IBinder? = null
}
