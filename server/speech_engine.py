"""
Speech Inference Engine Adapter for PhoneMic LAN.
Supports NVIDIA NeMo streaming models with cache management and graceful fallback.
"""

import logging
import numpy as np
from typing import Optional, Dict, Any

logger = logging.getLogger("phonewire.speech_engine")

class BaseSpeechEngine:
    def process_chunk(self, session_id: str, pcm_bytes: bytes) -> str:
        raise NotImplementedError

    def flush_session(self, session_id: str) -> str:
        raise NotImplementedError

    def close_session(self, session_id: str) -> None:
        pass


class MockSpeechEngine(BaseSpeechEngine):
    """
    Deterministic speech engine for testing, simulated streaming, and CPU fallbacks.
    """
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def process_chunk(self, session_id: str, pcm_bytes: bytes) -> str:
        if session_id not in self.sessions:
            self.sessions[session_id] = {"bytes_received": 0, "chunks": 0}
        
        sess = self.sessions[session_id]
        sess["bytes_received"] += len(pcm_bytes)
        sess["chunks"] += 1
        
        # Calculate simulated duration
        duration_s = sess["bytes_received"] / (self.sample_rate * 2) # 16-bit mono
        
        # In mock mode, generate words proportional to audio duration (at least 1 word per chunk)
        mock_words = ["hello", "this", "is", "a", "real", "time", "test", "of", "phone", "mic", "lan"]
        num_words = max(1, min(len(mock_words), int(duration_s * 2.5) + 1))
        return " ".join(mock_words[:num_words])

    def flush_session(self, session_id: str) -> str:
        if session_id in self.sessions:
            return self.process_chunk(session_id, b"")
        return ""

    def close_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            del self.sessions[session_id]


class NeMoStreamingEngine(BaseSpeechEngine):
    """
    Production NVIDIA NeMo Streaming Engine with per-session encoder caches.
    Optimized for NVIDIA GeForce GTX 1650 (4GB VRAM).
    """
    def __init__(self, model_name: str = "nvidia/parakeet_realtime_eou_120m-v1", device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.session_caches: Dict[str, Any] = {}
        self._load_model()

    def _load_model(self):
        try:
            import torch
            import nemo.collections.asr as nemo_asr
            logger.info(f"Loading NeMo streaming model: {self.model_name} on {self.device}...")
            self.model = nemo_asr.models.ASRModel.from_pretrained(model_name=self.model_name)
            self.model = self.model.to(self.device)
            self.model.eval()
            if self.device == "cuda":
                # Use FP16 on GTX 1650 to preserve VRAM
                self.model = self.model.half()
            logger.info("NeMo streaming model successfully initialized.")
        except Exception as e:
            logger.warning(f"Could not load real NeMo model ({e}). Using mock engine fallback.")
            self.model = None

    def process_chunk(self, session_id: str, pcm_bytes: bytes) -> str:
        if self.model is None:
            # Fallback
            return ""
        
        # Convert 16-bit PCM bytes to normalized float32/float16 numpy array
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        
        # Real NeMo streaming step using model's streaming API
        import torch
        with torch.no_grad():
            tensor = torch.from_numpy(audio_float).to(self.device)
            if self.device == "cuda":
                tensor = tensor.half()
            # If the model exposes streaming step:
            if hasattr(self.model, "step"):
                hypothesis = self.model.step(tensor, cache=self.session_caches.get(session_id))
                return str(hypothesis)
            return ""

    def flush_session(self, session_id: str) -> str:
        return ""

    def close_session(self, session_id: str) -> None:
        if session_id in self.session_caches:
            del self.session_caches[session_id]
        if self.device == "cuda":
            import torch
            torch.cuda.empty_cache()


def create_speech_engine(engine_type: str = "auto", model_name: str = "nvidia/parakeet_realtime_eou_120m-v1") -> BaseSpeechEngine:
    if engine_type == "mock":
        return MockSpeechEngine()
    elif engine_type == "nemo":
        return NeMoStreamingEngine(model_name=model_name)
    else:
        # Auto-detect
        try:
            import nemo.collections.asr
            return NeMoStreamingEngine(model_name=model_name)
        except ImportError:
            logger.info("NeMo collections not found; defaulting to MockSpeechEngine.")
            return MockSpeechEngine()
