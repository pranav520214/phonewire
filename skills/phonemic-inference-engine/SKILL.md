---
name: phonemic-inference-engine
description: Manages NVIDIA NeMo streaming ASR setup, GPU VRAM profiling on GTX 1650 (4GB), streaming encoder cache management, latency benchmarking, and audio chunk ingestion.
---

# Phonemic Inference Engine Skill

This skill governs the speech-to-text inference tier for PhoneMic LAN, utilizing NVIDIA NeMo on an NVIDIA GeForce GTX 1650 (4GB VRAM).

## Hardware & Runtime Rules

1. **VRAM Hard Ceiling:**
   - Physical VRAM: 4096 MiB.
   - Operating baseline (Windows Desktop / DWM): ~1040 MiB used.
   - Available budget for PyTorch + NeMo: **~3000 MiB maximum**.
   - If memory allocation exceeds 3100 MiB, immediately abort or unload to prevent CUDA Out Of Memory (OOM).

2. **Model Selection & Precedence:**
   - **Candidate A (Default):** `nvidia/parakeet_realtime_eou_120m-v1` (~120M parameters, ~240-450MB FP16).
     - Minimal VRAM footprint, fast streaming inference, suitable for 4GB hardware.
   - **Candidate B (Benchmarked Option):** `nvidia/nemotron-speech-streaming-en-0.6b` (~600M parameters, ~1.8-2.5GB).
     - Must only be enabled if full streaming benchmark passes with peak VRAM <= 3100 MiB and latency is lower than acceptable limits.

3. **Isolated Python Environment (`uv`):**
   - Use `uv` for reproducible environment management in `inference/`.
   - Python: 3.11 / 3.12.
   - PyTorch: `torch` with CUDA 12.4/12.6 support (`+cu124` or `+cu126`).
   - Pin dependencies in `inference/pyproject.toml` and lock via `uv lock`.

4. **Streaming Inference Execution Pattern:**
   - Audio format: 16 kHz, 16-bit Mono PCM.
   - Streaming frame chunk: 80ms (1280 samples) to 160ms (2560 samples).
   - Cache maintenance: Keep streaming encoder state (`cache_last_channel`, `cache_last_time`) persistent per active WebSocket session.
   - End-of-Stream (EOS): Upon EOS frame, invoke model finalizer/flush, extract final tokens, and reset/free session encoder cache to prevent memory leaks.

5. **Validation & Benchmarking:**
   - Before deploying: Run `scripts/benchmark_streaming.py` with standard sample audio.
   - Record First-Partial Latency (ms), Finalization Latency (ms), and Peak VRAM (MiB).
