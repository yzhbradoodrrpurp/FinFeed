import base64
import json
import os
import unittest
from unittest.mock import patch
from deployment.mihomo_runtime import private_config


class MihomoCases(unittest.TestCase):
    def encoded(self, **extra):
        return base64.b64encode(json.dumps({"proxies": [{"type": "trojan", "server": "proxy.example", "password": "private-node-password", **extra}],
                                           "external-controller": "0.0.0.0:9090", "allow-lan": True,
                                           "rules": ["MATCH,DIRECT"]}).encode()).decode()

    def test_only_loopback_is_exposed_and_rules_cannot_bypass_proxy(self):
        cfg = private_config(self.encoded())
        self.assertEqual(cfg["bind-address"], "127.0.0.1")
        self.assertFalse(cfg["allow-lan"])
        self.assertEqual(cfg["external-controller"], "")
        self.assertEqual(cfg["rules"], ["MATCH,upstream"])

    def test_tls_bypass_requires_explicit_opt_in_and_errors_are_redacted(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError) as caught:
            private_config(self.encoded(**{"skip-cert-verify": True}))
        self.assertNotIn("private-node-password", str(caught.exception))

    def test_invalid_secret_is_not_in_error(self):
        with self.assertRaises(ValueError) as caught:
            private_config("private-invalid-secret")
        self.assertNotIn("private-invalid-secret", str(caught.exception))
