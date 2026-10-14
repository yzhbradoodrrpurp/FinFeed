"""Recover only a stalled FinFeed tunnel, while its local API remains healthy."""
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
import time
from urllib.request import build_opener, ProxyHandler


class RecoveryGate:
    def __init__(self):
        self.failures = 0
        self.last_recovery = None

    def check(self, local_ok, public_ok, now):
        if public_ok or not local_ok:
            self.failures = 0
            return False
        self.failures += 1
        if self.failures < 3 or (self.last_recovery is not None and now - self.last_recovery < 900):
            return False
        self.failures = 0
        self.last_recovery = now
        return True


def healthy(url):
    try:
        # Avoid inherited market proxy configuration and retain TLS verification.
        with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
            return response.status == 200 and json.loads(response.read(1024)).get('ok') is True
    except Exception:
        return False


def recover(root):
    pid = int((root / '.runtime/tailscale.pid').read_text())
    proc = Path('/proc') / str(pid)
    command = proc.joinpath('cmdline').read_bytes().split(b'\0')
    expected = str(root / '.tailscale/tailscaled').encode()
    if command[0] != expected or b'--socket=@finfeed-h20-control' not in command:
        raise RuntimeError('Unexpected tunnel process')
    if proc.joinpath('cwd').resolve() != root / 'app/dashboard' or os.getpgid(pid) != pid:
        raise RuntimeError('Unexpected tunnel process ownership')
    supervisor = int((root / '.runtime/supervisor.pid').read_text())
    if str(root / 'app/dashboard/deployment/h20/supervise.py').encode() not in (Path('/proc') / str(supervisor) / 'cmdline').read_bytes():
        raise RuntimeError('FinFeed supervisor is unavailable')
    os.killpg(pid, signal.SIGTERM)


def start():
    root = Path(os.environ['FINFEED_H20_ROOT']).resolve()
    runtime = root / '.runtime'
    if not runtime.is_dir():
        return

    def run():
        lock = (runtime / 'tunnel-watchdog.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return
        gate = RecoveryGate()
        # Keep cooldown across backend reloads.
        status_file = runtime / 'tunnel-watchdog.json'
        try:
            previous = json.loads(status_file.read_text())
            last = previous.get('last_recovery')
            if isinstance(last, (int, float)):
                gate.last_recovery = time.monotonic() - max(0, time.time() - last)
        except (OSError, ValueError, TypeError, AttributeError):
            previous = {}
        time.sleep(60)
        while True:
            local = healthy('http://127.0.0.1:18765/api/health')
            public = healthy('https://finfeed.tail03a68f.ts.net/api/health') if local else False
            # One working public route is sufficient; do not restart for a single edge outage.
            if local and not public:
                public = healthy('https://finfeed-research.vercel.app/api/health')
            status = {'checked_at': time.time(), 'local_ok': local, 'public_ok': public,
                      'last_recovery': previous.get('last_recovery')}
            if gate.check(local, public, time.monotonic()):
                try:
                    recover(root)
                    status['last_recovery'] = time.time()
                    status['action'] = 'tunnel_restart'
                except Exception as error:
                    status['action'] = 'recovery_rejected'
                    status['error_type'] = type(error).__name__
            status['consecutive_failures'] = gate.failures
            temp = status_file.with_suffix('.tmp')
            temp.write_text(json.dumps(status))
            os.replace(temp, status_file)
            previous = status
            time.sleep(60)

    threading.Thread(target=run, daemon=True, name='finfeed-tunnel-watchdog').start()
