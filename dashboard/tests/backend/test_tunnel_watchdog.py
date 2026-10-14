import unittest
from deployment.h20.tunnel_watchdog import RecoveryGate, recover
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class TunnelWatchdogCases(unittest.TestCase):
    def test_requires_three_public_failures_and_local_success(self):
        gate = RecoveryGate()
        self.assertFalse(gate.check(True, False, 0))
        self.assertFalse(gate.check(True, False, 60))
        self.assertFalse(gate.check(False, False, 120))
        self.assertFalse(gate.check(True, False, 180))
        self.assertFalse(gate.check(True, False, 240))
        self.assertTrue(gate.check(True, False, 300))

    def test_recovery_cooldown_and_success_reset(self):
        gate = RecoveryGate()
        for now in [0, 60]:
            self.assertFalse(gate.check(True, False, now))
        self.assertFalse(gate.check(True, True, 120))
        for now in [180, 240]:
            self.assertFalse(gate.check(True, False, now))
        self.assertTrue(gate.check(True, False, 300))
        for now in [360, 420, 480, 1199]:
            self.assertFalse(gate.check(True, False, now))
        self.assertTrue(gate.check(True, False, 1200))

    def test_unverified_process_is_never_signalled(self):
        import os
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.runtime').mkdir()
            (root / '.runtime/tailscale.pid').write_text(str(os.getpid()))
            with patch.object(Path, 'read_bytes', return_value=b'python\0'), patch('deployment.h20.tunnel_watchdog.os.killpg') as kill:
                with self.assertRaisesRegex(RuntimeError, 'Unexpected tunnel process'):
                    recover(root)
                kill.assert_not_called()
