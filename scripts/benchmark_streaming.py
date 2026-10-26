"""
Streaming ASR Latency & VRAM Benchmarking Harness for PhoneMic LAN.
Measures First-Partial Latency, Finalization Latency, and Peak GPU VRAM.
"""

import sys
import os
import time
import struct
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.speech_engine import create_speech_engine
from server.assembler import TranscriptAssembler

def get_vram_mb() -> float:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024 * 1024)
    except Exception:
        pass
    return 0.0

def run_benchmark():
    print("=" * 65)
    print("       PhoneMic LAN — Streaming Inference Feasibility Test")
    print("=" * 65)

    import torch
    cuda_avail = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_avail else "CPU (None)"
    print(f"Device:               {gpu_name}")
    print(f"CUDA Available:       {cuda_avail}")
    baseline_vram = get_vram_mb()
    print(f"Baseline PyTorch VRAM: {baseline_vram:.2f} MiB")

    model_name = "nvidia/parakeet_realtime_eou_120m-v1"
    print(f"\nInitializing Speech Engine ({model_name})...")
    engine = create_speech_engine(model_name=model_name)
    assembler = TranscriptAssembler()
    
    loaded_vram = get_vram_mb()
    print(f"Engine Loaded VRAM:    {loaded_vram:.2f} MiB")

    # Generate 3 seconds of synthetic 16kHz 16-bit Mono audio (48,000 samples)
    sample_rate = 16000
    chunk_samples = 2560 # 160ms chunks
    num_chunks = 20 # 3.2 seconds total
    
    session_id = "bench-session-001"
    first_partial_latency_ms = None
    chunk_latencies = []
    
    print(f"\nStreaming {num_chunks} chunks (160ms each, {num_chunks * 0.16:.1f}s audio total)...")
    
    t_start_stream = time.perf_counter()
    for i in range(num_chunks):
        # 16-bit PCM chunk
        chunk_pcm = (np.random.randn(chunk_samples) * 1000).astype(np.int16).tobytes()
        
        t0 = time.perf_counter()
        hypo = engine.process_chunk(session_id, chunk_pcm)
        t1 = time.perf_counter()
        
        chunk_latencies.append((t1 - t0) * 1000)
        
        if hypo and first_partial_latency_ms is None:
            first_partial_latency_ms = (t1 - t_start_stream) * 1000
            assembler.update_hypothesis(hypo)

    # Flush
    t_flush_start = time.perf_counter()
    engine.flush_session(session_id)
    final_text = assembler.finalize()
    t_flush_end = time.perf_counter()
    finalization_latency_ms = (t_flush_end - t_flush_start) * 1000

    peak_vram = get_vram_mb()
    engine.close_session(session_id)

    print("\n--- Benchmark Results ---")
    print(f"First-Partial Latency:    {first_partial_latency_ms:.2f} ms" if first_partial_latency_ms else "First-Partial Latency:    N/A")
    print(f"Finalization Latency:     {finalization_latency_ms:.2f} ms")
    print(f"Avg Chunk Inference Time: {np.mean(chunk_latencies):.2f} ms per 160ms chunk")
    print(f"Real-Time Factor (RTF):   {(np.mean(chunk_latencies) / 160.0):.4f}x (< 1.0 is faster than real-time)")
    print(f"Peak VRAM during stream:  {peak_vram:.2f} MiB")
    print(f"Final Assembled Text:     \"{final_text}\"")
    print("=" * 65)

if __name__ == "__main__":
    run_benchmark()
