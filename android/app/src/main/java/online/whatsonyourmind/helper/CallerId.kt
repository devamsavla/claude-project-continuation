package online.whatsonyourmind.helper

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.telecom.Call
import android.telecom.CallScreeningService
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Caller ID without uploading anyone's contacts: when a call rings, only the incoming number is checked against
 *  Mindy's community scam reports and verified businesses. Calls are never blocked unless the person turned that on. */
class CallerId : CallScreeningService() {
    override fun onScreenCall(details: Call.Details) {
        val number = details.handle?.schemeSpecificPart ?: ""
        val incoming = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || details.callDirection == Call.Details.DIRECTION_INCOMING
        if (number.isEmpty() || !incoming) return respond(details, false)
        Thread {
            val info = lookup(this, number)
            val reports = info?.optInt("reports", 0) ?: 0
            val verified = info?.optString("verified", "")?.takeIf { it.isNotEmpty() && it != "null" }
            val block = reports >= 5 && Prefs(this).blockScams
            respond(details, block)
            when {
                verified != null -> notify(this, "✅ $verified", "Verified business on Mindy: $number")
                reports >= 2 -> notify(this, "🚩 Likely scam call", "$reports people reported $number. Don't share OTPs or pay." + if (block) " Mindy silenced it." else "")
            }
        }.start()
    }

    private fun respond(details: Call.Details, block: Boolean) {
        val r = CallResponse.Builder()
        if (block) r.setDisallowCall(true).setRejectCall(true).setSkipNotification(false).setSkipCallLog(false)
        respondToCall(details, r.build())
    }

    companion object {
        fun lookup(ctx: Context, number: String): JSONObject? = try {
            val c = URL(Prefs(ctx).server + "/api/number/" + URLEncoder.encode(number, "UTF-8")).openConnection() as HttpURLConnection
            c.connectTimeout = 3000; c.readTimeout = 3000
            val t = if (c.responseCode == 200) c.inputStream.bufferedReader().use { it.readText() } else null
            c.disconnect()
            t?.let { JSONObject(it) }
        } catch (e: Exception) { null }

        fun notify(ctx: Context, title: String, text: String) {
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(NotificationChannel("calls", "Caller ID", NotificationManager.IMPORTANCE_HIGH))
            val n = (if (Build.VERSION.SDK_INT >= 26) android.app.Notification.Builder(ctx, "calls") else android.app.Notification.Builder(ctx))
                .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(text)
                .setStyle(android.app.Notification.BigTextStyle().bigText(text)).setAutoCancel(true).build()
            nm.notify((System.currentTimeMillis() % 100000).toInt(), n)
        }
    }
}
