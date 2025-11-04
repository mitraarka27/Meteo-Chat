# mcp_server/main.py
"""
Minimal MCP server stub so `python -m mcp_server.main` works.
Replace with your actual server startup logic (FastAPI, Flask, etc.).
"""

import time

def main():
    print("[mcp_server] server started on http://127.0.0.1:8787")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[mcp_server] shutting down...")

if __name__ == "__main__":
    main()