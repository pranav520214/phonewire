"""
FastAPI WebSocket Streaming and Authentication Server for PhoneMic LAN.
"""

import sys
import os
import struct
import uuid
import time
import logging
from typing import Optional, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database import (
    init_db,
    create_enrollment_code,
    verify_enrollment_code,
    validate_bearer_token,
    create_session,
    close_session,
    save_transcript,
    update_insertion_status,
    get_transcripts,
    DEFAULT_DB_PATH,
)
from server.assembler import TranscriptAssembler
from server.speech_engine import create_speech_engine, BaseSpeechEngine
from windows_agent.inserter import WindowsTextInserter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("phonewire.server")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized via lifespan. PhoneMic LAN Server ready.")
    yield

# Global singletons
speech_engine: BaseSpeechEngine = create_speech_engine()
inserter = WindowsTextInserter(restore_clipboard=True)
active_sessions: Dict[str, dict] = {}

app = FastAPI(title="PhoneMic LAN Server", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Proactively ensure db exists
init_db()

# Models
class PairRequest(BaseModel):
    code: str
    device_name: str = "Redmi Note 7 Pro"

class InsertRequest(BaseModel):
    transcript_id: str
    text: Optional[str] = None

# Auth helper
def get_current_device(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    device = validate_bearer_token(token)
    if not device:
        raise HTTPException(status_code=401, detail="Unauthorized device token")
    return device

# Routes
@app.get("/v1/health")
def health_check():
    import torch
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "CPU"
    return {
        "status": "healthy",
        "service": "PhoneMic LAN",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "active_sessions": len(active_sessions),
    }

@app.post("/v1/pair/code")
def generate_code():
    code = create_enrollment_code()
    logger.info(f"Generated new pairing code: {code}")
    return {"code": code, "expires_in_seconds": 300}

@app.post("/v1/pair/verify")
def verify_code(req: PairRequest):
    token = verify_enrollment_code(req.code, req.device_name)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code")
    return {
        "token": token,
        "token_type": "bearer",
        "device_name": req.device_name,
    }

@app.get("/v1/history")
def list_history(q: Optional[str] = None, limit: int = 50, _dev: dict = Depends(get_current_device)):
    return {"transcripts": get_transcripts(query=q, limit=limit)}

@app.post("/v1/insert")
def manual_insert(req: InsertRequest, _dev: dict = Depends(get_current_device)):
    transcripts = get_transcripts()
    matched = next((t for t in transcripts if t["id"] == req.transcript_id), None)
    text = req.text or (matched["refined_text"] or matched["raw_text"] if matched else None)
    if not text:
        raise HTTPException(status_code=404, detail="Transcript text not found")
    
    res = inserter.insert_text(text, insertion_id=f"manual-{req.transcript_id}")
    return res

@app.websocket("/v1/stream")
async def websocket_stream(websocket: WebSocket, token: Optional[str] = Query(None)):
    await websocket.accept()
    
    # Authenticate via token query param or initial auth header
    device = validate_bearer_token(token) if token else None
    if not device:
        # Check first incoming JSON message for auth
        try:
            init_msg = await websocket.receive_json()
            if init_msg.get("type") == "auth":
                client_token = init_msg.get("token")
                device = validate_bearer_token(client_token) if client_token else None
            if not device:
                await websocket.send_json({"type": "error", "message": "Authentication failed"})
                await websocket.close(code=1008)
                return
        except Exception:
            await websocket.close(code=1008)
            return

    session_id = str(uuid.uuid4())
    create_session(session_id, device["id"])
    assembler = TranscriptAssembler()
    auto_insert = True
    active_sessions[session_id] = {"device": device, "started_at": time.time()}

    await websocket.send_json({
        "type": "session_started",
        "session_id": session_id,
        "device_id": device["id"],
    })

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                raw_data = message["bytes"]
                # Header: seq_num (4 bytes uint32), timestamp (8 bytes uint64) = 12 bytes
                if len(raw_data) > 12:
                    seq_num, ts = struct.unpack(">IQ", raw_data[:12])
                    pcm_bytes = raw_data[12:]
                else:
                    pcm_bytes = raw_data

                # Feed speech engine
                chunk_hypo = speech_engine.process_chunk(session_id, pcm_bytes)
                if chunk_hypo:
                    committed, full = assembler.update_hypothesis(chunk_hypo)
                    await websocket.send_json({
                        "type": "partial",
                        "committed": committed,
                        "provisional": assembler.provisional_text,
                        "full": full,
                    })

            elif "text" in message and message["text"]:
                data = await websocket.receive_json() if False else None
                # Parse text frame as json
                import json
                try:
                    ctrl = json.loads(message["text"])
                except Exception:
                    continue

                m_type = ctrl.get("type")
                if m_type == "config":
                    auto_insert = ctrl.get("auto_insert", True)
                elif m_type == "eos":
                    # End of stream requested: finalize transcript
                    speech_engine.flush_session(session_id)
                    final_text = assembler.finalize()
                    transcript_id = str(uuid.uuid4())
                    
                    insertion_res = {"status": "DISABLED"}
                    if auto_insert and final_text:
                        insertion_res = inserter.insert_text(final_text, insertion_id=transcript_id)

                    save_transcript(
                        transcript_id=transcript_id,
                        session_id=session_id,
                        raw_text=assembler.get_committed_text(),
                        refined_text=final_text,
                        model_name="nvidia/parakeet_realtime_eou_120m-v1",
                        inserted=(insertion_res.get("status") == "SUCCESS"),
                        insertion_status=insertion_res.get("status", "FAILED"),
                        error=insertion_res.get("message") if insertion_res.get("status") != "SUCCESS" else None,
                    )

                    await websocket.send_json({
                        "type": "final",
                        "transcript_id": transcript_id,
                        "text": final_text,
                        "inserted": (insertion_res.get("status") == "SUCCESS"),
                        "insertion_status": insertion_res.get("status"),
                        "details": insertion_res,
                    })
                elif m_type == "cancel":
                    speech_engine.close_session(session_id)
                    await websocket.send_json({"type": "cancelled"})
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error in session {session_id}: {e}")
    finally:
        speech_engine.close_session(session_id)
        close_session(session_id)
        if session_id in active_sessions:
            del active_sessions[session_id]
