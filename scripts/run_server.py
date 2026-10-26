"""
CLI runner for PhoneMic LAN Server.
Detects local LAN IP, shows enrollment pairing instructions, and starts Uvicorn.
"""

import sys
import os
import socket
import uvicorn

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database import init_db, create_enrollment_code

def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect, just resolves outbound route
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def main():
    init_db()
    lan_ip = get_lan_ip()
    port = 8000
    code = create_enrollment_code()
    
    print("=" * 60)
    print("        🎙️  PhoneMic LAN Server Starting...  🎙️")
    print("=" * 60)
    print(f"  Local LAN Address:  http://{lan_ip}:{port}")
    print(f"  WebSocket URL:      ws://{lan_ip}:{port}/v1/stream")
    print(f"  Active Pairing Code: [{code}] (valid for 5 minutes)")
    print("=" * 60)
    print("Open the PhoneMic Android app, enter the IP and Pairing Code above.")
    print("Press Ctrl+C to terminate the server.\n")

    uvicorn.run("server.app:app", host="0.0.0.0", port=port, log_level="info")

if __name__ == "__main__":
    main()
