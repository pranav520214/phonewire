---
name: phonemic-windows-agent
description: Manages Windows interactive desktop text insertion, Win32 SendInput emulation, atomic clipboard swap and restore, foreground window safety checks, and automated Notepad verification.
---

# Phonemic Windows Agent Skill

This skill governs the automated text insertion into focused Windows desktop applications (Notepad, web browsers, IDEs) using native Win32 APIs.

## Insertion Principles & Safety

1. **User-Session Process:**
   - Must run inside the interactive user desktop session (`session 1`).
   - Must NEVER run as a detached service or headless daemon that lacks access to the desktop message pump.

2. **Pre-Insertion Safety Checks:**
   - Call `GetForegroundWindow()`.
   - Verify the desktop is unlocked and not showing secure credential dialogs (e.g. UAC prompts, lock screen, password fields).
   - Verify target window handle (`HWND`) is non-null.
   - If focus changed during transcription and safety fails, do NOT paste. Mark insertion as `SKIPPED_UNFOCUSED` and notify client.

3. **Atomic Clipboard Swap & Restore:**
   ```
   Original Clipboard Content -> Backed up to memory
   Final Transcript -> Placed into CF_UNICODETEXT clipboard format
   SendInput(Ctrl + V) -> Emulated keyboard events (VK_CONTROL, 'V')
   Wait (30-50ms) -> Ensure target window message pump receives WM_PASTE
   Restore -> Put original clipboard content back (ONLY if clipboard text hasn't been modified by user)
   ```

4. **Exactly-Once Insertion Guarantee:**
   - Every insertion operation receives a unique UUID (`insertion_id`).
   - Maintain a local idempotency ledger in memory and SQLite.
   - Reject any duplicate insertion requests for an existing `insertion_id`.

5. **Automated Verification Harness:**
   - Automated tests must launch a controlled `notepad.exe` process.
   - Focus Notepad edit control.
   - Trigger insertion.
   - Read edit control contents via `WM_GETTEXT`.
   - Assert exact string match (including Unicode and multiline).
   - Terminate test Notepad process cleanly without prompt dialogs.
