---
name: phonemic-android-client
description: Develops, configures, and tests the Android Kotlin & Jetpack Compose microphone streaming client for Redmi Note 7 Pro, AudioRecord 16kHz PCM capture, OkHttp WebSocket resilience, and Room storage.
---

# Phonemic Android Client Skill

This skill governs the Android application for PhoneMic LAN, targeting devices like the Redmi Note 7 Pro (Android 9/10/11+, minSdk 28, targetSdk 34).

## Architecture & Implementation Principles

1. **Audio Capture Engine:**
   - Use `AudioRecord` (not `MediaRecorder`, to avoid container encoding latency).
   - Audio Source: `MediaRecorder.AudioSource.VOICE_RECOGNITION` (applies hardware noise suppression/beamforming) with fallback to `MIC`.
   - Sample Rate: 16,000 Hz.
   - Channel: `AudioFormat.CHANNEL_IN_MONO`.
   - Encoding: `AudioFormat.ENCODING_PCM_16BIT`.
   - Chunk size: 100ms (1600 samples = 3200 bytes) or 160ms (2560 samples = 5120 bytes).

2. **Network Resilience (OkHttp WebSocket):**
   - Use OkHttp with coroutines and `Channel<ByteArray>` for non-blocking packet dispatch.
   - Maintain sequence numbers and packet timestamps.
   - Ping/Pong heartbeats every 15 seconds.
   - Graceful reconnect upon Wi-Fi handover without losing recorded frames.

3. **Jetpack Compose UI Requirements:**
   - **Main Screen:**
     - Large microphone floating button with tactile/visual recording feedback.
     - Real-time audio amplitude visualizer (VU meter) calculated from PCM RMS.
     - Live partial transcript area showing real-time feedback.
     - Finalized transcript card with insertion state badge (`Inserted`, `Copied`, `Failed`).
     - Manual "Copy" and "Retry Insertion" controls.
   - **Settings Screen:**
     - Server Host IP and Port configuration.
     - 6-digit pairing code entry with status indicator.
     - Automatic Insertion toggle (default ON).
     - Local retention and history clear option.
   - **History Screen:**
     - Offline searchable list of previous voice typing transcripts stored in local Room DB.

4. **Lifecycle & Permissions:**
   - Request `RECORD_AUDIO` permission with rationale dialog.
   - Run microphone streaming inside a Foreground Service with notification to prevent OS killer suspension while app is in background.
   - Listen to `AudioManager` audio focus changes (pause capture when incoming phone call arrives).

5. **Build & Tooling:**
   - Gradle build with Version Catalog (`gradle/libs.versions.toml`).
   - Clean architecture: `audio/`, `network/`, `data/`, `ui/`.
   - Target APK assembly via `./gradlew assembleDebug` or `assembleRelease`.
