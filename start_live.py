"""
start_live.py — Launch the MSNR live web terminal (FastAPI + TradingView dashboard).

Usage:
    python start_live.py                 # http://127.0.0.1:8000
    python start_live.py --port 8080     # custom port
    python start_live.py --host 0.0.0.0 --port 8000  # LAN access

Requires: fastapi, uvicorn  (pip install -r requirements.txt fastapi "uvicorn[standard]")
MT5 terminal should be installed + logged in; without it the API still runs
but candle/strategy endpoints will error instead of serving live data.
"""

import argparse
import importlib.util
import os
import sys

# Self-healing interpreter: the bot needs the Python 3.11 install (numpy,
# pandas, MetaTrader5, ...). Some shells resolve `python` to another venv
# (e.g. hermes-agent) that lacks them. In that case, re-exec this script
# with the correct interpreter instead of crashing with ModuleNotFoundError.
NEEDED = ("pandas", "numpy")
GOOD_PYTHON = r"C:\Users\Hp\AppData\Local\Programs\Python\Python311\python.exe"


def _ensure_interpreter(argv):
    if os.environ.get("MSNR_REEXEC") == "1":
        return  # already re-exec'd once; report the real error below
    missing = [m for m in NEEDED if importlib.util.find_spec(m) is None]
    if not missing:
        return
    if os.path.isfile(GOOD_PYTHON):
        print(f"`{sys.executable}` lacks: {', '.join(missing)}")
        print(f"Re-launching with {GOOD_PYTHON} ...")
        os.environ["MSNR_REEXEC"] = "1"
        # NOTE: os.execv on Windows joins args without quoting, so a script
        # path containing spaces (e.g. "trading bot") must be quoted manually.
        script = os.path.abspath(__file__)
        os.execv(GOOD_PYTHON, [GOOD_PYTHON, f'"{script}"'] + argv[1:])
    print(f"ERROR: current interpreter lacks: {', '.join(missing)}")
    print(f"Fix with:  \"{GOOD_PYTHON}\" -m pip install -r requirements.txt")


_ensure_interpreter(sys.argv)

# Always run from this script's directory so `server`, `config`, etc. import.
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BOT_DIR)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)


def check_deps():
    missing = []
    for pkg in ("pandas", "numpy", "fastapi", "uvicorn"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"ERROR: missing packages: {', '.join(missing)}")
        print(f"Fix with:  \"{sys.executable}\" -m pip install -r requirements.txt fastapi \"uvicorn[standard]\"")
        sys.exit(1)


def _silence_accept_noise():
    """Windows IOCP proactor noise: when a client aborts its connection
    during the TCP accept (typical on browser refresh / keep-alive churn),
    asyncio's accept coroutine raises WinError 64 ("The specified network
    name is no longer available") and logs it from inside stdlib's asyncio
    and proactor-event machinery — uvicorn keeps accepting, nothing is
    broken. Filter ONLY that one error; everything else still logs."""
    import logging

    class _WinErr64Filter(logging.Filter):
        def filter(self, record):
            # Fast path: the accept-failure tracebacks print their context
            # inside the message text itself.
            text = record.getMessage()
            if ("The specified network name is no longer available" in text
                    or "WinError 64" in text
                    or "Accept failed on a socket" in text):
                return False
            # Slow path: records logged with exc_info carry the OSError
            # there; walk the chain, only WinError 64 is silenced.
            exc = record.exc_info[1] if record.exc_info else None
            while exc is not None:
                if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 64:
                    return False
                exc = exc.__cause__ or exc.__context__
            return True

    noise = _WinErr64Filter()
    for name in ("asyncio", "uvicorn.error", "uvicorn"):
        logging.getLogger(name).addFilter(noise)


def main():
    parser = argparse.ArgumentParser(description="MSNR live web terminal")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    args = parser.parse_args()

    check_deps()
    _silence_accept_noise()

    import webbrowser
    import threading
    import uvicorn

    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"Starting MSNR live web terminal -> {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("server:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
