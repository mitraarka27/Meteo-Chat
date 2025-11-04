# meteo_chat/mcp_client.py
import time
import socket
import requests

def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False

def is_http_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False