"""
Windows Desktop Text Inserter for PhoneMic LAN.
Handles foreground validation, atomic clipboard swap & restore, and Win32 SendInput Ctrl+V.
"""

import ctypes
from ctypes import wintypes
import time
import uuid
import logging
from typing import Optional, Tuple

logger = logging.getLogger("phonewire.inserter")

# Win32 Constants
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
GHND = GMEM_MOVEABLE | GMEM_ZEROINIT

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

# ctypes structures for SendInput
wintypes.ULONG_PTR = ctypes.c_ulong if ctypes.sizeof(ctypes.c_void_p) == 4 else ctypes.c_ulonglong

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.ULONG_PTR),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Function prototypes
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

user32.GetClassNameW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

user32.OpenClipboard.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [wintypes.HWND]

user32.CloseClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []

user32.EmptyClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []

user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]

user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

user32.SendInput.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]

kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]

kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def get_foreground_info() -> Tuple[int, str, str]:
    """Returns (hwnd, window_title, class_name) of the active window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0, "", ""
    
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    
    return hwnd, title_buf.value, class_buf.value


def get_clipboard_text() -> Optional[str]:
    """Reads current unicode text from the clipboard."""
    for _ in range(5):
        if user32.OpenClipboard(0):
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return None
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return None
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        time.sleep(0.01)
    return None


def set_clipboard_text(text: str) -> bool:
    """Sets unicode text to the clipboard."""
    encoded = text.encode("utf-16le") + b"\x00\x00"
    h_mem = kernel32.GlobalAlloc(GHND, len(encoded))
    if not h_mem:
        return False
    
    ptr = kernel32.GlobalLock(h_mem)
    if not ptr:
        return False
    
    ctypes.memmove(ptr, encoded, len(encoded))
    kernel32.GlobalUnlock(h_mem)
    
    for _ in range(5):
        if user32.OpenClipboard(0):
            try:
                user32.EmptyClipboard()
                if user32.SetClipboardData(CF_UNICODETEXT, h_mem):
                    return True
            finally:
                user32.CloseClipboard()
        time.sleep(0.01)
    return False


def send_paste_keystrokes() -> bool:
    """Simulates Ctrl + V keystroke using Win32 SendInput."""
    inputs = (INPUT * 4)()
    
    # 0: Ctrl down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].u.ki.wVk = VK_CONTROL
    inputs[0].u.ki.dwFlags = 0
    
    # 1: V down
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].u.ki.wVk = VK_V
    inputs[1].u.ki.dwFlags = 0
    
    # 2: V up
    inputs[2].type = INPUT_KEYBOARD
    inputs[2].u.ki.wVk = VK_V
    inputs[2].u.ki.dwFlags = KEYEVENTF_KEYUP
    
    # 3: Ctrl up
    inputs[3].type = INPUT_KEYBOARD
    inputs[3].u.ki.wVk = VK_CONTROL
    inputs[3].u.ki.dwFlags = KEYEVENTF_KEYUP
    
    sent = user32.SendInput(4, inputs, ctypes.sizeof(INPUT))
    return sent == 4


class WindowsTextInserter:
    """
    Manages stateful text insertion with clipboard restoration and idempotency.
    """
    def __init__(self, restore_clipboard: bool = True):
        self.restore_clipboard = restore_clipboard
        self._processed_ids = set()

    def insert_text(self, text: str, insertion_id: Optional[str] = None) -> dict:
        """
        Inserts text into the currently focused Windows application.
        Returns result dict with status and details.
        """
        if not text:
            return {"status": "SKIPPED_EMPTY", "message": "Text is empty"}
        
        op_id = insertion_id or str(uuid.uuid4())
        if op_id in self._processed_ids:
            return {"status": "DUPLICATE_IGNORED", "message": f"Operation {op_id} already executed"}
        
        hwnd, title, class_name = get_foreground_info()
        if not hwnd:
            return {"status": "SKIPPED_NO_FOCUS", "message": "No active foreground window"}
        
        # Block pasting into lockscreen / credential screens
        if class_name in ("LockScreenUIHost", "Credential Dialog Xaml Host"):
            return {"status": "BLOCKED_SECURE_DESKTOP", "message": f"Target is secure window: {class_name}"}

        # Backup existing clipboard
        original_clipboard = get_clipboard_text() if self.restore_clipboard else None
        
        try:
            # Place transcript on clipboard
            if not set_clipboard_text(text):
                return {"status": "CLIPBOARD_ERROR", "message": "Failed to set clipboard data"}
            
            # Send Ctrl+V
            if not send_paste_keystrokes():
                return {"status": "SENDINPUT_ERROR", "message": "Failed to send Ctrl+V keystrokes"}
            
            # Allow target window message pump to process WM_PASTE
            time.sleep(0.04)
            
            self._processed_ids.add(op_id)
            return {
                "status": "SUCCESS",
                "insertion_id": op_id,
                "target_window": title,
                "target_class": class_name,
                "text_length": len(text)
            }
        finally:
            if self.restore_clipboard and original_clipboard is not None:
                # Only restore if clipboard still contains what we placed there
                current = get_clipboard_text()
                if current == text:
                    set_clipboard_text(original_clipboard)
