package com.phonemic.app.network

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class PhoneMicWebSocketClient(
    private val host: String,
    private val port: Int,
    private val token: String,
    private val onSessionStarted: (String) -> Unit,
    private val onPartial: (String, String) -> Unit, // committed, full
    private val onFinal: (String, Boolean, String) -> Unit, // text, inserted, status
    private val onError: (String) -> Unit
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val seqCounter = AtomicInteger(0)

    fun connect() {
        val url = "ws://$host:$port/v1/stream?token=$token"
        val request = Request.Builder().url(url).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                seqCounter.set(0)
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    when (json.optString("type")) {
                        "session_started" -> {
                            val sessionId = json.optString("session_id")
                            onSessionStarted(sessionId)
                        }
                        "partial" -> {
                            val committed = json.optString("committed")
                            val full = json.optString("full")
                            onPartial(committed, full)
                        }
                        "final" -> {
                            val finalText = json.optString("text")
                            val inserted = json.optBoolean("inserted", false)
                            val status = json.optString("insertion_status", "UNKNOWN")
                            onFinal(finalText, inserted, status)
                        }
                        "error" -> {
                            onError(json.optString("message", "Unknown error"))
                        }
                    }
                } catch (e: Exception) {
                    onError("Failed to parse server message: ${e.message}")
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                onError("WebSocket failure: ${t.message}")
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                // Closed gracefully
            }
        })
    }

    fun sendAudioChunk(pcmBytes: ByteArray) {
        val seq = seqCounter.incrementAndGet()
        val ts = System.currentTimeMillis()
        
        // 12-byte header: seq (4 bytes), ts (8 bytes)
        val buffer = ByteBuffer.allocate(12 + pcmBytes.size)
        buffer.putInt(seq)
        buffer.putLong(ts)
        buffer.put(pcmBytes)
        
        webSocket?.send(buffer.array().toByteString())
    }

    fun sendEos() {
        val json = JSONObject().apply {
            put("type", "eos")
        }
        webSocket?.send(json.toString())
    }

    fun sendConfig(autoInsert: Boolean) {
        val json = JSONObject().apply {
            put("type", "config")
            put("auto_insert", autoInsert)
        }
        webSocket?.send(json.toString())
    }

    fun disconnect() {
        webSocket?.close(1000, "Client closing")
        webSocket = null
    }
}
