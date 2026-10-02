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


def main():
    parser = argparse.ArgumentParser(description="MSNR live web terminal")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    args = parser.parse_args()

    check_deps()

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
