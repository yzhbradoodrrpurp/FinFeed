"""Oracle transport/startup contracts without infrastructure or real mail."""
import gzip
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from deployment import start, mihomo_runtime
from deployment.oracle import tick


class OracleDeploymentCases(unittest.TestCase):
    def test_loopback_bind_keeps_single_worker_and_existing_threads(self):
        with patch.dict(os.environ, {'FINFEED_BIND': '127.0.0.1:10000', 'MIHOMO_CONFIG_B64': ''}), patch.object(start.os, 'chdir'), patch.object(start.os, 'execvp', side_effect=SystemExit) as execute, self.assertRaises(SystemExit):
            start.main()
        args = execute.call_args.args[1]
        self.assertEqual(args[args.index('--bind') + 1], '127.0.0.1:10000')
        self.assertEqual(args[args.index('--workers') + 1], '1')
        self.assertEqual(args[args.index('--threads') + 1], '64')

    def test_scheduler_calls_loopback_with_backend_host_and_bearer(self):
        response = MagicMock()
        response.__enter__.return_value.status = 202
        with patch.dict(os.environ, {'PUBLIC_ORIGIN': 'https://backend.example.com', 'FINFEED_NOTIFICATION_CRON_TOKEN': 'x' * 40}), patch.object(tick, 'urlopen', return_value=response) as send:
            tick.main()
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:10000/api/notifications/tick')
        self.assertEqual(request.get_header('Host'), 'backend.example.com')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + 'x' * 40)
        self.assertEqual(request.data, b'{}')

    def test_scheduler_failure_does_not_expose_credentials(self):
        with patch.dict(os.environ, {'PUBLIC_ORIGIN': 'https://backend.example.com', 'FINFEED_NOTIFICATION_CRON_TOKEN': 'x' * 40}), patch.object(tick, 'urlopen', side_effect=RuntimeError('secret')), self.assertRaises(SystemExit) as caught:
            tick.main()
        self.assertNotIn('secret', str(caught.exception))

    def test_proxy_selects_arm_asset_and_rejects_tampered_download(self):
        with patch.object(mihomo_runtime.platform, 'system', return_value='Linux'), patch.object(mihomo_runtime.platform, 'machine', return_value='aarch64'), patch.object(mihomo_runtime.urllib.request, 'urlopen', return_value=io.BytesIO(b'tampered')) as fetch, self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
            mihomo_runtime.install()
        self.assertIn('mihomo-linux-arm64-', fetch.call_args.args[0])

    def test_valid_pinned_proxy_archive_is_installed_executable(self):
        archive = gzip.compress(b'test executable')
        with tempfile.TemporaryDirectory() as directory, patch.object(mihomo_runtime, 'BINARY', Path(directory) / 'runtime' / 'mihomo'), patch.object(mihomo_runtime.platform, 'system', return_value='Linux'), patch.object(mihomo_runtime.platform, 'machine', return_value='x86_64'), patch.object(mihomo_runtime, 'SHA256', hashlib.sha256(archive).hexdigest()), patch.object(mihomo_runtime.urllib.request, 'urlopen', return_value=io.BytesIO(archive)):
            mihomo_runtime.install()
            self.assertEqual(mihomo_runtime.BINARY.read_bytes(), b'test executable')
            self.assertEqual(mihomo_runtime.BINARY.stat().st_mode & 0o777, 0o700)
