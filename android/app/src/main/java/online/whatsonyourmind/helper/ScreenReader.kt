package online.whatsonyourmind.helper

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/** One thing on screen that Mindy can point at. */
class Item(val index: Int, val node: AccessibilityNodeInfo, val rect: Rect, val password: Boolean, val label: String)

/**
 * Turns the current screen into a short list of visible buttons, boxes and labels.
 * Only text and positions are read, never a screenshot, which keeps it private and cheap.
 */
object ScreenReader {
    private val SENSITIVE = Regex("(?i)\\b(upi pin|enter pin|mpin|otp|one.?time|cvv|password|passcode|atm pin)\\b")

    fun read(root: AccessibilityNodeInfo?, max: Int = 120): Pair<JSONArray, List<Item>> {
        val arr = JSONArray()
        val items = ArrayList<Item>()
        if (root == null) return Pair(arr, items)
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while (queue.isNotEmpty() && items.size < max) {
            val n = queue.removeFirst()
            for (i in 0 until n.childCount) {
                n.getChild(i)?.let { queue.add(it) }
            }
            if (!n.isVisibleToUser) continue
            val text = n.text?.toString()?.trim()?.take(80) ?: ""
            val desc = n.contentDescription?.toString()?.trim()?.take(80) ?: ""
            val hint = n.hintText?.toString()?.trim()?.take(60) ?: ""
            val useful = text.isNotEmpty() || desc.isNotEmpty() || hint.isNotEmpty() || n.isClickable || n.isEditable
            if (!useful) continue
            val rect = Rect()
            n.getBoundsInScreen(rect)
            if (rect.width() <= 2 || rect.height() <= 2) continue
            val idx = items.size
            val password = n.isPassword
            val o = JSONObject().put("i", idx)
            if (!password) {
                if (text.isNotEmpty()) o.put("t", text)
                if (desc.isNotEmpty()) o.put("d", desc)
            }
            if (hint.isNotEmpty()) o.put("h", hint)
            n.viewIdResourceName?.substringAfterLast('/')?.let { o.put("id", it.take(40)) }
            if (n.isClickable) o.put("k", 1)
            if (n.isEditable) o.put("e", 1)
            if (n.isScrollable) o.put("s", 1)
            if (password) o.put("p", 1)
            arr.put(o)
            items.add(Item(idx, n, rect, password, text.ifEmpty { desc.ifEmpty { hint } }))
        }
        return Pair(arr, items)
    }

    /** PIN, OTP, password or card screens: Mindy looks away. */
    fun sensitive(items: List<Item>): Boolean =
        items.any { it.password || SENSITIVE.containsMatchIn(it.label) }

    /** The nearest clickable parent, for tapping a label inside a button. */
    fun clickable(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        var n = node
        var depth = 0
        while (n != null && depth < 6) {
            if (n.isClickable) return n
            n = n.parent
            depth++
        }
        return null
    }
}
