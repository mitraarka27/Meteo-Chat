# meteo_chat/cli.py
import os
import sys
import signal
import time
import subprocess
import webbrowser
import http.client
import urllib.parse
from pathlib import Path

from meteo_chat.mcp_client import wait_for_port  # simple TCP connect probe

# ---- Paths & defaults -------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

APP_PATH = ROOT / "apps" / "streamlit_app" / "app.py"
MCP_NODE_DIR = ROOT / "mcp_server"                 # Node/TS MCP lives here by default
PKG_JSON = MCP_NODE_DIR / "package.json"

# Base URLs. NOTE: app.py posts directly to LLM_URL (expects /generate)
DEFAULT_MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8787")
DEFAULT_LLM_BASE = os.environ.get("LLM_BASE", "http://127.0.0.1:8899")
DEFAULT_LLM_URL  = os.environ.get("LLM_URL", f"{DEFAULT_LLM_BASE}/generate")

# Strong default for your local adapter (no user export needed)
DEFAULT_ADAPTER_PATH = os.environ.get(
    "ADAPTER_PATH",
    "/Users/mitra/vibe_code/weatherai/artifacts/adapter"
)

APP_HOST = "127.0.0.1"
APP_PORT = int(os.getenv("STREAMLIT_SERVER_PORT", "8501"))
MCP_DEFAULT_PORT = 8787
LLM_DEFAULT_PORT = 8899


# ---- Utilities ---------------------------------------------------------------
def _parse_host_port(url: str):
    """Extract host/port from http://host[:port][/...] with graceful fallback."""
    host = "127.0.0.1"
    port = None
    try:
        rest = url.split("://", 1)[-1]
        hostpart = rest.split("/")[0]
        if ":" in hostpart:
            host, port_s = hostpart.split(":")[0], hostpart.split(":")[1]
            port = int(port_s)
        else:
            host = hostpart
    except Exception:
        pass
    return host, port


def _wait_http_ok(url: str, timeout=60):
    """
    Poll a URL until it returns a 2xx status or timeout.
    Useful for hitting /health on the LLM server.
    """
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    t0 = time.time()

    while time.time() - t0 < timeout:
        try:
            conn = http.client.HTTPConnection(host, port, timeout=3)
            conn.request("GET", path)
            resp = conn.getresponse()
            if 200 <= resp.status < 300:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _env_with_defaults():
    env = os.environ.copy()
    env.setdefault("MCP_URL", DEFAULT_MCP_URL)
    env.setdefault("LLM_URL", DEFAULT_LLM_URL)            # app posts to /generate
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    return env


# ---- LLM launcher ------------------------------------------------------------
def run_llm():
    """
    Start the FastAPI LLM service (weatherai.agent.llm_service).
    Forces ADAPTER_PATH to your local artifacts; binds to 127.0.0.1:8899.
    """
    env = os.environ.copy()
    env["ADAPTER_PATH"] = DEFAULT_ADAPTER_PATH     # hard default so user doesn't export
    env.setdefault("LLM_PORT", str(LLM_DEFAULT_PORT))

    # Use module execution so imports resolve from installed package
    cmd = [sys.executable, "-m", "weatherai.agent.llm_service"]
    # No special cwd needed if package is installed; keep at ROOT for safety.
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env)


# ---- MCP launchers -----------------------------------------------------------
def _run_mcp_node():
    """
    Start Node/TS MCP via npm scripts if mcp_server/ exists.
    Prefers `npm run dev`, falls back to `npm start`.
    """
    if not PKG_JSON.exists():
        return None

    env = _env_with_defaults()

    try:
        # Assume deps present. If not, try install once.
        if not (MCP_NODE_DIR / "node_modules").exists():
            subprocess.run(["npm", "i"], cwd=str(MCP_NODE_DIR), env=env, check=False)
        return subprocess.Popen(["npm", "run", "dev"], cwd=str(MCP_NODE_DIR), env=env)
    except FileNotFoundError:
        # npm not on PATH
        return None
    except Exception:
        return None


def _run_mcp_python():
    """
    Fallback: start a Python MCP if available (mcp_server.main).
    """
    env = _env_with_defaults()
    try:
        # Prefer module execution
        return subprocess.Popen(
            [sys.executable, "-m", "mcp_server.main", "--port", str(MCP_DEFAULT_PORT)],
            env=env
        )
    except Exception:
        # Fallback to file path under apps/ if present
        main_py = ROOT / "apps" / "mcp_server" / "main.py"
        if main_py.exists():
            return subprocess.Popen(
                [sys.executable, str(main_py), "--port", str(MCP_DEFAULT_PORT)],
                env=env
            )
        return None


def run_mcp():
    """
    Public function: runs MCP only (foreground).
    """
    proc = _run_mcp_node()
    if proc is None:
        proc = _run_mcp_python()

    if proc is None:
        print("[meteo-chat] ERROR: Could not find a runnable MCP server. "
              "Install Node MCP under mcp_server/ or provide a Python MCP at apps/mcp_server/main.py.",
              file=sys.stderr)
        sys.exit(2)

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


# ---- Streamlit app launcher --------------------------------------------------
def run_app():
    """
    Public function: runs Streamlit app only (foreground).
    """
    if not APP_PATH.exists():
        print(f"[meteo-chat] App not found: {APP_PATH}", file=sys.stderr)
        sys.exit(1)

    env = _env_with_defaults()
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP_PATH),
        "--server.address", APP_HOST,
        "--server.port", str(APP_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
    ]
    proc = subprocess.Popen(cmd, env=env)

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


# ---- One-shot launcher -------------------------------------------------------
def main():
    """
    Starts MCP -> waits for port,
    starts LLM -> waits for /health,
    starts Streamlit -> waits for port -> opens browser.
    Cleanly shuts down all on Ctrl+C.
    """
    # 1) MCP
    print("[meteo-chat] Starting MCP server...")
    mcp_proc = _run_mcp_node()
    if mcp_proc is None:
        mcp_proc = _run_mcp_python()
    if mcp_proc is None:
        print("[meteo-chat] ERROR: Unable to launch any MCP server.", file=sys.stderr)
        sys.exit(2)

    mcp_host, mcp_port = _parse_host_port(DEFAULT_MCP_URL)
    if mcp_port is None:
        mcp_port = MCP_DEFAULT_PORT
    if not wait_for_port(mcp_host, mcp_port, timeout=60):
        print("[meteo-chat] MCP port didn't open in time. Exiting.", file=sys.stderr)
        try:
            mcp_proc.terminate()
        finally:
            sys.exit(3)

    # 2) LLM
    print("[meteo-chat] Starting LLM server...")
    llm_proc = run_llm()
    if not _wait_http_ok(f"{DEFAULT_LLM_BASE}/health", timeout=120):
        print("[meteo-chat] LLM /health not ready. Exiting.", file=sys.stderr)
        try:
            llm_proc.terminate()
        finally:
            try:
                mcp_proc.terminate()
            finally:
                sys.exit(4)

    # 3) Streamlit
    print("[meteo-chat] Starting Streamlit app…")
    env = _env_with_defaults()
    app_cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP_PATH),
        "--server.address", APP_HOST,
        "--server.port", str(APP_PORT),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
    ]
    app_proc = subprocess.Popen(app_cmd, env=env)

    # 4) Wait for app port, then open browser
    if wait_for_port(APP_HOST, APP_PORT, timeout=90):
        try:
            webbrowser.open(f"http://{APP_HOST}:{APP_PORT}", new=2, autoraise=True)
        except Exception:
            pass
        print(f"[meteo-chat] App is up: http://{APP_HOST}:{APP_PORT}")
    else:
        print("[meteo-chat] App port did not open in time; you can try opening "
              f"http://{APP_HOST}:{APP_PORT} manually.", file=sys.stderr)

    # Graceful shutdown
    def _shutdown(*_):
        print("\n[meteo-chat] Shutting down...")
        for p in (app_proc, llm_proc, mcp_proc):
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(0.6)
        for p in (app_proc, llm_proc, mcp_proc):
            try:
                p.kill()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # If app exits, bring others down
    exit_code = 0
    try:
        exit_code = app_proc.wait()
    finally:
        try:
            llm_proc.terminate()
        except Exception:
            pass
        try:
            mcp_proc.terminate()
        except Exception:
            pass
    sys.exit(exit_code)


if __name__ == "__main__":
    main()