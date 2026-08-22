package com.pllsim.app

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.system.Os
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * A WebView shell around pllsim.appbridge.
 *
 * All Python runs on one background thread: the engines are plain numpy code
 * with no locking, and a single-lane executor makes "one run at a time" a
 * property of the app rather than a discipline the UI must maintain.  The
 * first call also pays the import of numpy/scipy/matplotlib (several
 * seconds on a phone), which is why module lookup happens inside the
 * executor and the page shows its own loading state until then.
 */
class MainActivity : Activity() {

    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var web: WebView
    private var bridge: PyObject? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) {
            // matplotlib writes its font cache on first import and dies on a
            // read-only config dir; this must be set before Python starts.
            val mpl = filesDir.resolve("mpl").apply { mkdirs() }
            Os.setenv("MPLCONFIGDIR", mpl.path, true)
            Python.start(AndroidPlatform(this))
        }
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.addJavascriptInterface(HostBridge(), "host")
        setContentView(web)
        web.loadUrl("file:///android_asset/www/index.html")
    }

    inner class HostBridge {
        /** Async RPC: returns immediately; the reply lands via onHostReply. */
        @JavascriptInterface
        fun call(id: String, method: String, argsJson: String) {
            executor.execute {
                val reply = try {
                    val py = bridge ?: Python.getInstance()
                        .getModule("pllsim.appbridge").also { bridge = it }
                    py.callAttr("call", method, argsJson).toString()
                } catch (e: Exception) {
                    // same in-band envelope the Python side uses, so the page
                    // has exactly one error path
                    JSONObject().put("ok", false)
                        .put("error", e.toString()).toString()
                }
                runOnUiThread {
                    web.evaluateJavascript(
                        "window.onHostReply(${JSONObject.quote(id)}," +
                            "${JSONObject.quote(reply)})", null)
                }
            }
        }
    }
}
