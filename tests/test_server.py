"""
Unit and integration tests for PhoneMic LAN Server, Protocol, and Database.
"""

import sys
import os
import struct
import time
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.app import app
from server.database import (
    init_db,
    create_enrollment_code,
    verify_enrollment_code,
    validate_bearer_token,
    save_transcript,
    get_transcripts,
)
from server.assembler import TranscriptAssembler

client = TestClient(app)

def test_database_and_auth_lifecycle(tmp_path):
    test_db = str(tmp_path / "test_phonemic.db")
    init_db(test_db)
    
    # 1. Generate pairing code
    code = create_enrollment_code(test_db, ttl_seconds=60)
    assert len(code) == 6
    assert code.isdigit()
    
    # 2. Verify pairing code
    token = verify_enrollment_code(code, "Test Redmi Note 7 Pro", test_db)
    assert token is not None
    assert token.startswith("pm_")
    
    # Code cannot be reused
    reuse = verify_enrollment_code(code, "Second Device", test_db)
    assert reuse is None
    
    # 3. Validate bearer token
    device = validate_bearer_token(token, test_db)
    assert device is not None
    assert device["device_name"] == "Test Redmi Note 7 Pro"
    
    # Invalid token check
    invalid = validate_bearer_token("pm_nonexistent", test_db)
    assert invalid is None

def test_transcript_assembler():
    asm = TranscriptAssembler()
    
    # First chunk
    c1, f1 = asm.update_hypothesis("hello this is")
    assert f1 == "hello this is"
    
    # Commit
    asm.commit_provisional()
    assert asm.get_committed_text() == "hello this is"
    
    # Second chunk with overlapping boundary words ("this is a test")
    c2, f2 = asm.update_hypothesis("this is a test")
    # Should deduplicate "this is"
    assert f2 == "hello this is a test"
    
    # Finalize
    final_text = asm.finalize()
    assert final_text == "Hello this is a test."

def test_fastapi_health_endpoint():
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "gpu_available" in data
    assert "gpu_name" in data

def test_fastapi_pairing_and_history():
    # 1. Generate code
    res_code = client.post("/v1/pair/code")
    assert res_code.status_code == 200
    code = res_code.json()["code"]
    
    # 2. Verify code
    res_pair = client.post("/v1/pair/verify", json={"code": code, "device_name": "Redmi Note 7 Pro"})
    assert res_pair.status_code == 200
    token = res_pair.json()["token"]
    
    # 3. Fetch history with token
    headers = {"Authorization": f"Bearer {token}"}
    res_hist = client.get("/v1/history", headers=headers)
    assert res_hist.status_code == 200
    assert "transcripts" in res_hist.json()
    
    # 4. History without token fails
    res_unauth = client.get("/v1/history")
    assert res_unauth.status_code == 401

def test_websocket_streaming_flow():
    # Obtain auth token
    res_code = client.post("/v1/pair/code")
    code = res_code.json()["code"]
    res_pair = client.post("/v1/pair/verify", json={"code": code, "device_name": "Test Client"})
    token = res_pair.json()["token"]

    with client.websocket_connect(f"/v1/stream?token={token}") as ws:
        # First message is session start
        start_msg = ws.receive_json()
        assert start_msg["type"] == "session_started"
        session_id = start_msg["session_id"]
        assert session_id is not None
        
        # Send 160ms of 16kHz 16-bit mono PCM (zeros / tone)
        seq_num = 1
        ts_ms = int(time.time() * 1000)
        header = struct.pack(">IQ", seq_num, ts_ms)
        dummy_pcm = b"\x00" * 5120  # 2560 samples = 160ms
        packet = header + dummy_pcm
        
        ws.send_bytes(packet)
        partial_msg = ws.receive_json()
        assert partial_msg["type"] == "partial"
        assert "full" in partial_msg
        
        # Send EOS
        ws.send_json({"type": "eos"})
        final_msg = ws.receive_json()
        assert final_msg["type"] == "final"
        assert "transcript_id" in final_msg
        assert "text" in final_msg
        assert "inserted" in final_msg
