package com.phonemic.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.sqrt

class AudioStreamer(
    private val onChunkCaptured: (ByteArray, Float) -> Unit
) {
    private var audioRecord: AudioRecord? = null
    private var recordingJob: Job? = null
    private val sampleRate = 16000
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val chunkSamples = 2560 // 160ms per frame
    private val chunkBytes = chunkSamples * 2 // 16-bit = 2 bytes per sample

    @SuppressLint("MissingPermission")
    fun startRecording(scope: CoroutineScope): Boolean {
        if (recordingJob?.isActive == true) return true

        val minBufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        val bufferSize = maxOf(minBufferSize, chunkBytes * 4)

        try {
            audioRecord = try {
                AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    sampleRate,
                    channelConfig,
                    audioFormat,
                    bufferSize
                )
            } catch (e: Exception) {
                AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    sampleRate,
                    channelConfig,
                    audioFormat,
                    bufferSize
                )
            }

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                audioRecord?.release()
                audioRecord = null
                return false
            }

            audioRecord?.startRecording()
        } catch (e: Exception) {
            audioRecord?.release()
            audioRecord = null
            return false
        }

        recordingJob = scope.launch(Dispatchers.IO) {
            val buffer = ShortArray(chunkSamples)
            val byteBuffer = ByteArray(chunkBytes)

            while (isActive && audioRecord?.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                val readShorts = audioRecord?.read(buffer, 0, chunkSamples) ?: -1
                if (readShorts > 0) {
                    var sumSquares = 0.0
                    for (i in 0 until readShorts) {
                        val sample = buffer[i]
                        sumSquares += (sample * sample).toDouble()
                        byteBuffer[i * 2] = (sample.toInt() and 0xFF).toByte()
                        byteBuffer[i * 2 + 1] = ((sample.toInt() shr 8) and 0xFF).toByte()
                    }
                    val rms = sqrt(sumSquares / readShorts)
                    val normalizedRms = (rms / 32768.0).toFloat().coerceIn(0f, 1f)
                    
                    val payload = byteBuffer.copyOf(readShorts * 2)
                    onChunkCaptured(payload, normalizedRms)
                }
            }
        }
        return true
    }

    fun stopRecording() {
        recordingJob?.cancel()
        recordingJob = null
        try {
            if (audioRecord?.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                audioRecord?.stop()
            }
        } catch (e: Exception) {
            // Ignored
        } finally {
            audioRecord?.release()
            audioRecord = null
        }
    }
}
