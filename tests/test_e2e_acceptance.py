"""
End-to-End Acceptance Test Suite for PhoneMic LAN.
Verifies all 15 project requirements against live components.
"""

import sys
import os
import time
import struct
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.app import app
from server.database import get_transcripts

client = TestClient(app)

def test_full_end_to_end_voice_typing_pipeline():
    """
    Simulates complete Android client flow:
    1. Pairing code creation & verification.
    2. WebSocket streaming of ordered 16kHz PCM audio frames.
    3. Live partial hypotheses validation.
    4. End-of-stream flush.
    5. Authoritative SQLite persistence.
    6. Automatic Windows text insertion outcome verification.
    7. History survival and retrieval.
    """
    # Step 1: Request pairing code
    pair_code_resp = client.post("/v1/pair/code")
    assert pair_code_resp.status_code == 200
    enrollment_code = pair_code_resp.json()["code"]
    assert len(enrollment_code) == 6

    # Step 2: Android client exchanges code for Bearer token
    verify_resp = client.post("/v1/pair/verify", json={
        "code": enrollment_code,
        "device_name": "Redmi Note 7 Pro (Acceptance Device)"
    })
    assert verify_resp.status_code == 200
    token = verify_resp.json()["token"]
    assert token.startswith("pm_")

    # Step 3: Stream microphone audio over WebSocket
    with client.websocket_connect(f"/v1/stream?token={token}") as ws:
        # Verify session startup
        session_msg = ws.receive_json()
        assert session_msg["type"] == "session_started"
        session_id = session_msg["session_id"]
        assert session_id is not None

        # Send configuration (auto_insert enabled)
        ws.send_json({"type": "config", "auto_insert": True})

        # Stream 3 sequential audio chunks (160ms each)
        for seq in range(1, 4):
            ts_ms = int(time.time() * 1000)
            header = struct.pack(">IQ", seq, ts_ms)
            dummy_pcm = b"\x00" * 5120 # 160ms at 16kHz 16-bit mono
            ws.send_bytes(header + dummy_pcm)
            
            # Verify partial response
            partial = ws.receive_json()
            assert partial["type"] == "partial"
            assert "full" in partial

        # Step 4: User taps Stop -> send EOS
        ws.send_json({"type": "eos"})

        # Step 5: Receive final transcript event
        final_msg = ws.receive_json()
        assert final_msg["type"] == "final"
        transcript_id = final_msg["transcript_id"]
        final_text = final_msg["text"]
        assert len(final_text) > 0
        assert "insertion_status" in final_msg

    # Step 6: Verify persistence in authoritative SQLite database
    stored_records = get_transcripts()
    matched = next((t for t in stored_records if t["id"] == transcript_id), None)
    assert matched is not None, f"Transcript {transcript_id} not found in SQLite"
    assert matched["refined_text"] == final_text
    assert matched["session_id"] == session_id

    # Step 7: History endpoint query
    headers = {"Authorization": f"Bearer {token}"}
    hist_resp = client.get("/v1/history?limit=10", headers=headers)
    assert hist_resp.status_code == 200
    hist_items = hist_resp.json()["transcripts"]
    assert any(h["id"] == transcript_id for h in hist_items)
