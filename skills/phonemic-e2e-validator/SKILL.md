---
name: phonemic-e2e-validator
description: Orchestrates end-to-end integration testing, network fault simulation, first-partial and finalization latency benchmarks, and strict acceptance criteria verification.
---

# Phonemic E2E Validator Skill

This skill governs end-to-end integration testing, performance benchmarking, fault injection, and honest acceptance reporting for PhoneMic LAN.

## Testing Standards & Acceptance Criteria

1. **Strict Verification Rule:**
   - **Never claim a test passed without executing it.**
   - Every verification must produce machine-readable logs or assertion output.
   - If a test fails, report the exact failure trace and root cause.

2. **Automated End-to-End Test Suite:**
   - **Test 1: Streaming Latency Benchmark:**
     - Stream synthetic or recorded 16kHz WAV sample audio over WebSocket.
     - Measure time from audio frame transmission to first partial transcript received (target < 300ms).
     - Measure time from EOS frame to final transcript assembled (target < 500ms).
   - **Test 2: Word Deduplication & Assembly Test:**
     - Feed speech with overlapping chunks; assert final transcript does NOT contain stuttered or duplicate words at chunk boundaries.
   - **Test 3: Windows Desktop Insertion Test:**
     - Launch test Notepad process.
     - Transcribe known phrase: `"The quick brown fox jumps over the lazy dog."`
     - Verify Notepad text via Win32 `WM_GETTEXT`.
     - Confirm exactly one insertion without repetition.
   - **Test 4: Network Disconnection & Recovery:**
     - Abruptly terminate client socket during streaming.
     - Reconnect with session token; verify server gracefully handles dangling session without crash or VRAM leak.
   - **Test 5: Offline Autonomy Check:**
     - Verify all transcription operations function 100% offline without public internet connection.

3. **Benchmarking Log Format:**
   - Report must tabulate:
     - GPU Name & Driver
     - Baseline VRAM vs Peak Inference VRAM
     - First-Partial Latency (p50, p95)
     - Finalization Latency (p50, p95)
     - Insertion Latency
     - Pass/Fail state for all 15 project acceptance criteria
