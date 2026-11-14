package online.whatsonyourmind.helper

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.view.View

/** A pulsing green ring with an arrow, drawn on top of whatever app is open. It never blocks touches. */
class PointerView(ctx: Context) : View(ctx) {
    private val density = ctx.resources.displayMetrics.density
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f * density
        color = Color.rgb(37, 211, 102)
    }
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(60, 37, 211, 102)
    }
    private val arrow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.rgb(255, 92, 92)
    }
    private var target: Rect? = null
    private var pulse = 0f
    private val anim = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 1100
        repeatCount = ValueAnimator.INFINITE
        addUpdateListener {
            pulse = it.animatedValue as Float
            invalidate()
        }
    }

    fun point(r: Rect?) {
        target = r
        if (r != null && !anim.isStarted) anim.start()
        if (r == null) anim.cancel()
        invalidate()
    }

    override fun onDetachedFromWindow() {
        anim.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val r = target ?: return
        val loc = IntArray(2)
        getLocationOnScreen(loc)
        val cx = r.exactCenterX() - loc[0]
        val cy = r.exactCenterY() - loc[1]
        val base = (maxOf(r.width(), r.height()) / 2f).coerceIn(28f * density, 140f * density) + 10f * density
        canvas.drawCircle(cx, cy, base + pulse * 18f * density, glow)
        canvas.drawCircle(cx, cy, base, ring)
        // arrow pointing up at the ring from below (or down from above near the bottom of the screen)
        val below = cy + base + 90f * density < height
        val tipY = if (below) cy + base + 6f * density else cy - base - 6f * density
        val dir = if (below) 1f else -1f
        val p = Path()
        p.moveTo(cx, tipY)
        p.lineTo(cx - 18f * density, tipY + dir * 30f * density)
        p.lineTo(cx - 6f * density, tipY + dir * 30f * density)
        p.lineTo(cx - 6f * density, tipY + dir * (60f + pulse * 10f) * density)
        p.lineTo(cx + 6f * density, tipY + dir * (60f + pulse * 10f) * density)
        p.lineTo(cx + 6f * density, tipY + dir * 30f * density)
        p.lineTo(cx + 18f * density, tipY + dir * 30f * density)
        p.close()
        canvas.drawPath(p, arrow)
    }
}
