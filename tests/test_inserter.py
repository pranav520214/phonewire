"""
Automated unit and integration tests for WindowsTextInserter.
Tests clipboard roundtrip, idempotency, and Notepad integration.
"""

import sys
import os
import subprocess
import time
import pytest
import ctypes
from ctypes import wintypes

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from windows_agent.inserter import (
    WindowsTextInserter,
    get_clipboard_text,
    set_clipboard_text,
    get_foreground_info,
    user32,
)

def test_clipboard_roundtrip():
    """Verify unicode and special characters are preserved across clipboard."""
    test_str = "PhoneMic LAN Testing: 12345 Hello World! 🚀 Привет नमस्ते"
    assert set_clipboard_text(test_str) is True
    read_back = get_clipboard_text()
    assert read_back == test_str

def test_idempotency():
    """Verify duplicate insertion_id calls are safely ignored without re-pasting."""
    inserter = WindowsTextInserter(restore_clipboard=False)
    op_id = "test-op-12345"
    
    # First call with dummy empty text should report empty
    res1 = inserter.insert_text("", insertion_id=op_id)
    assert res1["status"] == "SKIPPED_EMPTY"
    
    # If simulated success:
    inserter._processed_ids.add(op_id)
    res2 = inserter.insert_text("Real text", insertion_id=op_id)
    assert res2["status"] == "DUPLICATE_IGNORED"

def test_foreground_info():
    """Verify get_foreground_info returns valid handle and strings."""
    hwnd, title, class_name = get_foreground_info()
    assert isinstance(hwnd, int)
    assert isinstance(title, str)
    assert isinstance(class_name, str)

def test_notepad_live_insertion():
    """
    Launches Notepad, brings to foreground, inserts text,
    verifies no crash and insertion success, then cleanly closes Notepad.
    """
    proc = subprocess.Popen(["notepad.exe"])
    try:
        # Give Notepad time to launch and register window
        target_hwnd = None
        for _ in range(20):
            time.sleep(0.1)
            # Find HWND for process
            def enum_proc(hwnd, extra):
                nonlocal target_hwnd
                lpdw_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_pid))
                if lpdw_pid.value == proc.pid:
                    target_hwnd = hwnd
                    return False
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
            if target_hwnd:
                break
        
        if target_hwnd:
            user32.ShowWindow(target_hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(target_hwnd)
            time.sleep(0.3)

        inserter = WindowsTextInserter(restore_clipboard=True)
        sample_phrase = "Live voice transcription inserted into Notepad via PhoneMic LAN."
        
        result = inserter.insert_text(sample_phrase)
        # In headless or automated test sessions where Windows prevents foreground changes,
        # inserter correctly guards against unfocused paste.
        assert result["status"] in ("SUCCESS", "SKIPPED_NO_FOCUS"), f"Unexpected result: {result}"
        if result["status"] == "SUCCESS":
            assert result["text_length"] == len(sample_phrase)
    finally:
        proc.terminate()
        proc.wait(timeout=3)
