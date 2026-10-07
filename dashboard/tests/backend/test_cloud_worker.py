"""Regression for Render preloading live psycopg pools before Gunicorn forks."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen
from test_store_connection import database_stub


class WorkerPoolCases(unittest.TestCase):
    def test_injected_preload_cannot_orphan_pool_workers(self):
        with database_stub() as (kwargs, _, _), tempfile.TemporaryDirectory() as directory:
            Path(directory, 'pool_app.py').write_text('''
import os, json
from psycopg_pool import ConnectionPool
created = os.getpid()
pool = ConnectionPool(kwargs=json.loads(os.environ['TEST_DB_OPTIONS']), min_size=0, max_size=2, timeout=1)
def app(environ, start_response):
    with pool.connection() as connection:
        connection.execute('SET test = 1')
    body = json.dumps(dict(created=created, current=os.getpid(), workers=all(t.is_alive() for t in pool._workers))).encode()
    start_response('200 OK', [('Content-Type','application/json')])
    return [body]
''')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            env = {**os.environ, 'GUNICORN_CMD_ARGS': '--preload',
                   'TEST_DB_OPTIONS': json.dumps(kwargs)}
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[2] / 'deployment/worker.py'),
                'pool_app:app', '--chdir', directory, '--bind', f'127.0.0.1:{port}',
                '--workers', '1', '--threads', '2'], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        with urlopen(f'http://127.0.0.1:{port}', timeout=2) as response:
                            result = json.load(response)
                        break
                    except Exception:
                        if time.monotonic() >= deadline or process.poll() is not None:
                            raise
                        time.sleep(0.05)
                self.assertEqual(result['created'], result['current'])
                self.assertNotEqual(result['current'], process.pid)
                self.assertTrue(result['workers'])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    unittest.main()
