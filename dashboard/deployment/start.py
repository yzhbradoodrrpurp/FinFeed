"""Supervise Gunicorn and an optional private loopback proxy on Render."""
import json
import os
import signal
import sys
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from deployment.mihomo_runtime import BINARY, PORT, private_config


def main():
    from backend.paths import DASHBOARD_ROOT
    os.chdir(DASHBOARD_ROOT)
    gunicorn = [sys.executable, str(Path(__file__).with_name("worker.py")), "backend.app:create_app()", "--bind", "0.0.0.0:" + os.environ.get("PORT", "10000"),
                "--workers", "1", "--threads", "64", "--timeout", "180"]
    encoded = os.environ.get("MIHOMO_CONFIG_B64", "")
    if not encoded:
        os.execvp(gunicorn[0], gunicorn)
    config = private_config(encoded)
    children = []

    def terminate(*args):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    with tempfile.TemporaryDirectory(prefix="finfeed-mihomo-") as directory:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        try:
            checked = subprocess.run([str(BINARY), "-t", "-d", directory, "-f", str(path)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if checked.returncode:
                raise RuntimeError("Mihomo configuration check failed")
            proxy = subprocess.Popen([str(BINARY), "-d", directory, "-f", str(path)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(proxy)
            deadline = time.monotonic() + 20
            while True:
                if proxy.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Mihomo loopback proxy failed to start")
                try:
                    with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
                        break
                except OSError:
                    time.sleep(0.2)
            os.environ["YAHOO_PROXY_URL"] = f"http://127.0.0.1:{PORT}"
            children.append(subprocess.Popen(gunicorn))
            print("Private Yahoo proxy ready on loopback", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(1)
            raise RuntimeError("A required service process stopped")
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
