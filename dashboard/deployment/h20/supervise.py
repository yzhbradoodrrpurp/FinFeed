"""Project-contained h20 services; no system service, TUN, or global network edits."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(os.environ.get('FINFEED_H20_ROOT', '/mnt/data/users/shx/FinFeed')).resolve()


def commands():
    services = {
        'proxy': [str(ROOT / '.proxy/mihomo'), '-d', str(ROOT / '.proxy'), '-f', str(ROOT / '.proxy/config.json')],
        'tailscale': [str(ROOT / '.tailscale/tailscaled'), '--tun=userspace-networking',
                      '--state=' + str(ROOT / '.tailscale/state'), '--statedir=' + str(ROOT / '.tailscale'),
                      '--socket=@finfeed-h20-control', '--port=0'],
        'backend': [str(ROOT / '.venv/bin/python'), str(ROOT / 'app/dashboard/deployment/h20/backend.py')],
    }
    if (ROOT / '.private/postgresql-enabled').exists():
        services = {'database': [str(ROOT / '.venv/bin/python'), str(ROOT / 'app/dashboard/deployment/h20/database.py')], **services}
        services['database-backup'] = [str(ROOT / '.venv/bin/python'), str(ROOT / 'app/dashboard/deployment/h20/database_backup.py')]
    if (ROOT / '.private/scheduler-enabled').exists():
        services['scheduler'] = [str(ROOT / '.venv/bin/python'), str(ROOT / 'app/dashboard/deployment/h20/scheduler.py')]
    return services


def main():
    if (ROOT / '.private/retired-deployment').exists():
        raise RuntimeError('This FinFeed deployment is retired; do not start a second database or Funnel identity')
    os.umask(0o077)
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    import fcntl
    lock = (runtime / 'supervisor.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    env = dict(os.environ)
    # Do not inherit the shared host's global proxy into application requests.
    for key in list(env):
        if key.lower() in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}:
            env.pop(key)
    env.update(json.loads((ROOT / '.private/backend.json').read_text()))
    env['YAHOO_PROXY_URL'] = 'http://127.0.0.1:17890'
    env['PYTHONPATH'] = str(ROOT / 'app/dashboard')
    children = {}
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    (runtime / 'supervisor.pid').write_text(str(os.getpid()))
    try:
        while not stopping:
            for name, cmd in commands().items():
                child = children.get(name)
                if child is not None and child.poll() is None:
                    continue
                child_env = dict(env)
                if name == 'proxy':
                    child_env = dict(os.environ)
                if name == 'tailscale':
                    # Only this daemon's control connections use the project proxy.
                    child_env = dict(os.environ)
                    child_env.update(HTTP_PROXY='http://127.0.0.1:17890', HTTPS_PROXY='http://127.0.0.1:17890',
                                     NO_PROXY='127.0.0.1,localhost', TS_NO_LOGS_NO_SUPPORT='true')
                log = (runtime / (name + '.log')).open('ab')
                try:
                    children[name] = subprocess.Popen(cmd, cwd=ROOT / 'app/dashboard', env=child_env,
                                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                                       start_new_session=True)
                finally:
                    log.close()
                (runtime / (name + '.pid')).write_text(str(children[name].pid))
                time.sleep(2)
            time.sleep(3)
    finally:
        for child in children.values():
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children.values():
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        (runtime / 'supervisor.pid').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
