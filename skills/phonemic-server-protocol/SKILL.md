---
name: phonemic-server-protocol
description: Manages the local FastAPI WebSocket streaming server, authenticated pairing via enrollment codes, sequence verification, backpressure, SQLite persistence, and transcript assembly.
---

# Phonemic Server Protocol Skill

This skill governs the local LAN server, WebSocket protocol, cryptographic authentication, and transcript assembly for PhoneMic LAN.

## Protocol & Architecture Rules

1. **Local Network Security & Pairing:**
   - Server runs on `0.0.0.0:8000` (or user-configured port), bound to the local private LAN only.
   - Initial pairing via 6-digit short-lived enrollment code displayed in server console/UI.
   - Client sends pairing request -> Server validates code -> Returns high-entropy device token (`Bearer <token>`).
   - Token is salted and hashed (SHA-256) before storing in SQLite `devices` table.
   - All subsequent HTTP and WebSocket endpoints require `Authorization: Bearer <token>`.

2. **WebSocket Streaming Packet Specification:**
   - Route: `/v1/stream?session_id=<UUID>`
   - Binary frame structure:
     - Header (12 bytes):
       - Sequence Number (`uint32`, 4 bytes): Monotonically increasing order.
       - Timestamp (`uint64`, 8 bytes): Client capture timestamp in milliseconds.
     - Payload: Raw 16 kHz 16-bit Mono PCM audio bytes.
   - JSON Control Messages:
     - `{"type": "start", "sample_rate": 16000, "channels": 1}`
     - `{"type": "eos"}` (End of stream)
     - `{"type": "cancel"}`

3. **Backpressure & Queue Management:**
   - Audio ingestion queue is bounded (max 50 frames, ~5-8 seconds of audio).
   - If inference lags and queue exceeds 35 frames:
     - Server sends `{"type": "backpressure", "queue_depth": N}` over WebSocket.
     - Phone UI displays a lag indicator.
     - Never drop frames silently.

4. **Transcript Assembler:**
   - Separates **committed text** (fixed history) from **provisional text** (active hypothesis).
   - Prevents duplicate words at chunk boundaries.
   - Sends incremental partial events:
     - `{"type": "partial", "committed": "...", "provisional": "..."}`
   - On EOS, flushes inference engine and yields authoritative `final` event:
     - `{"type": "final", "transcript_id": "<UUID>", "text": "..."}`

5. **Authoritative Persistence (SQLite):**
   - Tables: `transcripts`, `sessions`, `devices`, `insertion_log`.
   - Atomic transactions (`WAL` mode enabled for concurrent read/write).
   - Never delete a finalized transcript even if insertion or socket delivery fails.
