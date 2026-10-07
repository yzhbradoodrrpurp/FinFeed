"""Deployment and static URL contracts across the directory migration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.paths import DASHBOARD_ROOT
from backend.app import create_app, STATIC_ASSETS
from backend.storage.store import Store
from deployment import start

class LayoutCases(unittest.TestCase):
    def test_existing_static_urls_serve_exact_source_bytes(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(sqlite_path=str(Path(temporary.name) / 'state.sqlite'))
        app = create_app({'TESTING': True, 'PUBLIC_ORIGIN': 'http://localhost'}, store=store)
        client = app.test_client()
        for name, source in STATIC_ASSETS.items():
            if name in {'index.html', 'login.html'}:
                continue
            with self.subTest(name=name):
                response = client.get('/' + name)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, (DASHBOARD_ROOT/'frontend'/source).read_bytes())
        self.assertEqual(client.get('/login').data, (DASHBOARD_ROOT/'frontend/pages/login.html').read_bytes())
        self.assertEqual(client.get('/manifest.json').status_code, 404)

    def test_start_preserves_worker_and_concurrency(self):
        with patch.dict(start.os.environ, {'MIHOMO_CONFIG_B64': '', 'PORT': '10000'}), patch.object(start.os, 'chdir'), patch.object(start.os, 'execvp', side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                start.main()
        command = execute.call_args.args[1]
        self.assertTrue(Path(command[1]).is_file())
        self.assertIn('backend.app:create_app()', command)
        self.assertEqual(command[command.index('--workers')+1], '1')
        self.assertEqual(command[command.index('--threads')+1], '64')

    def test_probe_child_imports_with_production_cwd(self):
        subprocess.run([sys.executable, '-c', 'import backend.providers.yahoo.probe'], cwd=DASHBOARD_ROOT, check=True, capture_output=True)
