package online.whatsonyourmind.helper

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** Settings kept on the phone. */
class Prefs(ctx: Context) {
    private val p = ctx.getSharedPreferences("mindy", Context.MODE_PRIVATE)
    var token: String
        get() = p.getString("token", "") ?: ""
        set(v) = p.edit().putString("token", v).apply()
    var device: String
        get() {
            var d = p.getString("device", "") ?: ""
            if (d.isEmpty()) {
                d = UUID.randomUUID().toString()
                p.edit().putString("device", d).apply()
            }
            return d
        }
        set(v) = p.edit().putString("device", v).apply()
    var lang: String
        get() = p.getString("lang", "hi") ?: "hi"
        set(v) = p.edit().putString("lang", v).apply()
    var name: String
        get() = p.getString("name", "") ?: ""
        set(v) = p.edit().putString("name", v).apply()
    var familyPhone: String
        get() = p.getString("family", "") ?: ""
        set(v) = p.edit().putString("family", v).apply()
    var doIt: Boolean
        get() = p.getBoolean("doit", false)
        set(v) = p.edit().putBoolean("doit", v).apply()
    var blockScams: Boolean
        get() = p.getBoolean("block", false)
        set(v) = p.edit().putBoolean("block", v).apply()
    var gatewaySecret: String
        get() = p.getString("gw", "") ?: ""
        set(v) = p.edit().putString("gw", v).apply()
    var server: String
        get() = p.getString("server", BuildConfig.API_URL) ?: BuildConfig.API_URL
        set(v) = p.edit().putString("server", v.trimEnd('/')).apply()
}

/** Tiny HTTP client: JSON in, JSON out. Always call from a background thread. */
object Api {
    private fun call(ctx: Context, path: String, body: JSONObject, auth: Boolean): JSONObject? {
        val prefs = Prefs(ctx)
        return try {
            val c = URL(prefs.server + path).openConnection() as HttpURLConnection
            c.requestMethod = "POST"
            c.connectTimeout = 10000
            c.readTimeout = 25000
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            if (auth && prefs.token.isNotEmpty()) c.setRequestProperty("Authorization", "Bearer " + prefs.token)
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = c.responseCode
            val text = (if (code < 400) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            c.disconnect()
            if (code == 401 && auth) {
                prefs.token = ""
                null
            } else if (code < 400) JSONObject(text) else null
        } catch (e: Exception) {
            null
        }
    }

    /** Makes sure this phone has a Mindy account (no sign-up needed for the person). */
    fun ensureToken(ctx: Context): Boolean {
        val prefs = Prefs(ctx)
        if (prefs.token.isNotEmpty()) return true
        val body = JSONObject().put("device", prefs.device).put("lang", prefs.lang).put("tz", java.util.TimeZone.getDefault().id)
        if (prefs.name.isNotEmpty()) body.put("name", prefs.name)
        val r = call(ctx, "/api/helper/register", body, false) ?: return false
        prefs.token = r.optString("token", "")
        return prefs.token.isNotEmpty()
    }

    fun post(ctx: Context, path: String, body: JSONObject): JSONObject? {
        if (!ensureToken(ctx)) return null
        return call(ctx, path, body, true) ?: if (ensureToken(ctx)) call(ctx, path, body, true) else null
    }
}
