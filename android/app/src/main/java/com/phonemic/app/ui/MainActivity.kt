package com.phonemic.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.phonemic.app.audio.AudioStreamer
import com.phonemic.app.data.HistoryItem
import com.phonemic.app.network.PhoneMicWebSocketClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID

class MainActivity : ComponentActivity() {

    private var audioStreamer: AudioStreamer? = null
    private var wsClient: PhoneMicWebSocketClient? = null

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(this, "Microphone permission is required", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    PhoneMicScreen()
                }
            }
        }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun PhoneMicScreen() {
        val context = LocalContext.current
        val prefs = remember { context.getSharedPreferences("phonemic_prefs", Context.MODE_PRIVATE) }

        var serverIp by remember { mutableStateOf(prefs.getString("server_ip", "192.168.1.100") ?: "192.168.1.100") }
        var serverPort by remember { mutableStateOf(prefs.getString("server_port", "8000") ?: "8000") }
        var authToken by remember { mutableStateOf(prefs.getString("auth_token", "") ?: "") }
        var pairingCode by remember { mutableStateOf("") }
        var autoInsert by remember { mutableStateOf(prefs.getBoolean("auto_insert", true)) }

        var isRecording by remember { mutableStateOf(false) }
        var connectionState by remember { mutableStateOf("Disconnected") }
        var audioLevel by remember { mutableFloatStateOf(0f) }
        var livePartial by remember { mutableStateOf("") }
        var finalTranscript by remember { mutableStateOf("") }
        var lastStatus by remember { mutableStateOf("") }
        var showSettings by remember { mutableStateOf(false) }

        val historyList = remember { mutableStateListOf<HistoryItem>() }

        fun savePrefs() {
            prefs.edit()
                .putString("server_ip", serverIp)
                .putString("server_port", serverPort)
                .putString("auth_token", authToken)
                .putBoolean("auto_insert", autoInsert)
                .apply()
        }

        fun pairDevice() {
            lifecycleScope.launch(Dispatchers.IO) {
                try {
                    val client = OkHttpClient()
                    val json = JSONObject().apply {
                        put("code", pairingCode)
                        put("device_name", "Redmi Note 7 Pro")
                    }
                    val body = json.toString().toRequestBody("application/json".toMediaType())
                    val request = Request.Builder()
                        .url("http://$serverIp:$serverPort/v1/pair/verify")
                        .post(body)
                        .build()
                    val response = client.newCall(request).execute()
                    if (response.isSuccessful) {
                        val respJson = JSONObject(response.body?.string() ?: "{}")
                        val token = respJson.getString("token")
                        withContext(Dispatchers.Main) {
                            authToken = token
                            savePrefs()
                            Toast.makeText(context, "Pairing Successful!", Toast.LENGTH_SHORT).show()
                            showSettings = false
                        }
                    } else {
                        withContext(Dispatchers.Main) {
                            Toast.makeText(context, "Pairing Failed (Invalid Code)", Toast.LENGTH_SHORT).show()
                        }
                    }
                } catch (e: Exception) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(context, "Connection error: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        fun toggleRecording() {
            if (!isRecording) {
                if (authToken.isEmpty()) {
                    showSettings = true
                    Toast.makeText(context, "Please pair with PC first", Toast.LENGTH_SHORT).show()
                    return
                }

                connectionState = "Connecting..."
                livePartial = ""
                finalTranscript = ""
                lastStatus = ""

                wsClient = PhoneMicWebSocketClient(
                    host = serverIp,
                    port = serverPort.toIntOrNull() ?: 8000,
                    token = authToken,
                    onSessionStarted = {
                        connectionState = "Streaming"
                        wsClient?.sendConfig(autoInsert)
                    },
                    onPartial = { _, full ->
                        livePartial = full
                    },
                    onFinal = { text, inserted, status ->
                        finalTranscript = text
                        lastStatus = if (inserted) "Inserted into Windows" else "Saved ($status)"
                        isRecording = false
                        connectionState = "Ready"
                        historyList.add(0, HistoryItem(UUID.randomUUID().toString(), text, System.currentTimeMillis(), inserted, status))
                        audioStreamer?.stopRecording()
                    },
                    onError = { err ->
                        connectionState = "Error"
                        lastStatus = err
                        isRecording = false
                        audioStreamer?.stopRecording()
                    }
                )
                wsClient?.connect()

                audioStreamer = AudioStreamer { pcmBytes, level ->
                    audioLevel = level
                    wsClient?.sendAudioChunk(pcmBytes)
                }

                val ok = audioStreamer?.startRecording(lifecycleScope) ?: false
                if (ok) {
                    isRecording = true
                } else {
                    Toast.makeText(context, "Failed to start AudioRecord", Toast.LENGTH_SHORT).show()
                    wsClient?.disconnect()
                }
            } else {
                isRecording = false
                connectionState = "Finalizing..."
                audioStreamer?.stopRecording()
                wsClient?.sendEos()
            }
        }

        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("PhoneMic LAN", fontWeight = FontWeight.Bold) },
                    actions = {
                        IconButton(onClick = { showSettings = true }) {
                            Icon(Icons.Default.Settings, contentDescription = "Settings")
                        }
                    }
                )
            }
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.SpaceBetween
            ) {
                // Status Header
                AssistChip(
                    onClick = {},
                    label = { Text(connectionState) },
                    leadingIcon = {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(
                                    when (connectionState) {
                                        "Streaming" -> Color.Green
                                        "Connecting..." -> Color.Yellow
                                        "Ready" -> Color.Cyan
                                        "Error" -> Color.Red
                                        else -> Color.Gray
                                    }
                                )
                        )
                    }
                )

                // Live Partial Transcript or Final Result Card
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(200.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(16.dp),
                        verticalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = if (isRecording) {
                                if (livePartial.isNotEmpty()) livePartial else "Listening..."
                            } else {
                                if (finalTranscript.isNotEmpty()) finalTranscript else "Tap microphone to begin speaking"
                            },
                            fontSize = 18.sp,
                            lineHeight = 24.sp,
                            fontWeight = if (finalTranscript.isNotEmpty()) FontWeight.SemiBold else FontWeight.Normal,
                            color = if (isRecording) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
                        )

                        if (lastStatus.isNotEmpty()) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                SuggestionChip(
                                    onClick = {},
                                    label = { Text(lastStatus, fontSize = 12.sp) }
                                )

                                if (finalTranscript.isNotEmpty()) {
                                    IconButton(onClick = {
                                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                        clipboard.setPrimaryClip(ClipData.newPlainText("Transcript", finalTranscript))
                                        Toast.makeText(context, "Copied to clipboard", Toast.LENGTH_SHORT).show()
                                    }) {
                                        Icon(Icons.Default.ContentCopy, contentDescription = "Copy")
                                    }
                                }
                            }
                        }
                    }
                }

                // Audio Level VU Meter (Animated while recording)
                Row(
                    modifier = Modifier
                        .fillMaxWidth(0.6f)
                        .height(16.dp),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    val bars = 8
                    for (i in 0 until bars) {
                        val active = isRecording && (audioLevel * bars > i)
                        Box(
                            modifier = Modifier
                                .width(8.dp)
                                .fillMaxHeight(if (active) 1.0f else 0.25f)
                                .clip(RoundedCornerShape(4.dp))
                                .background(if (active) MaterialTheme.colorScheme.primary else Color.DarkGray)
                        )
                    }
                }

                // Central Big Microphone Button
                val scale by animateFloatAsState(
                    targetValue = if (isRecording) 1.15f else 1.0f,
                    animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
                    label = "mic_scale"
                )

                Box(
                    modifier = Modifier
                        .size(110.dp)
                        .scale(scale)
                        .clip(CircleShape)
                        .background(
                            if (isRecording) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary
                        )
                        .clickable { toggleRecording() },
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = if (isRecording) Icons.Default.MicOff else Icons.Default.Mic,
                        contentDescription = "Microphone",
                        modifier = Modifier.size(52.dp),
                        tint = Color.White
                    )
                }

                Spacer(modifier = Modifier.height(10.dp))
            }
        }

        // Settings Dialog
        if (showSettings) {
            AlertDialog(
                onDismissRequest = { showSettings = false },
                title = { Text("PC Connection Settings") },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedTextField(
                            value = serverIp,
                            onValueChange = { serverIp = it },
                            label = { Text("Windows PC LAN IP") },
                            singleLine = true
                        )
                        OutlinedTextField(
                            value = serverPort,
                            onValueChange = { serverPort = it },
                            label = { Text("Port (Default 8000)") },
                            singleLine = true
                        )
                        OutlinedTextField(
                            value = pairingCode,
                            onValueChange = { pairingCode = it },
                            label = { Text("6-Digit Pairing Code") },
                            singleLine = true
                        )
                        Button(
                            onClick = { pairDevice() },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("Pair with PC")
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("Auto-insert into Windows")
                            Switch(
                                checked = autoInsert,
                                onCheckedChange = {
                                    autoInsert = it
                                    savePrefs()
                                }
                            )
                        }
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        savePrefs()
                        showSettings = false
                    }) {
                        Text("Done")
                    }
                }
            )
        }
    }
}
