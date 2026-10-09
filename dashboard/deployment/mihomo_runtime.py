"""Optional single-node proxy sidecar for the existing Render web service."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import urllib.request

from backend.paths import DASHBOARD_ROOT as ROOT
BINARY = ROOT / ".cache" / "mihomo"
VERSION = "v1.19.32"
URL = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/mihomo-linux-amd64-compatible-{VERSION}.gz"
SHA256 = "ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20"
PORT = 17890


def install():
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in {"x86_64", "amd64", "aarch64", "arm64"}:
        raise RuntimeError("Mihomo build requires Linux amd64 or arm64")
    url, checksum = URL, SHA256
    if machine in {"aarch64", "arm64"}:
        url = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/mihomo-linux-arm64-{VERSION}.gz"
        # Pinned from the official release asset retrieved on 2026-10-09.
        checksum = "9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0"
    with urllib.request.urlopen(url, timeout=30) as response:
        archive = response.read(50_000_001)
    if len(archive) > 50_000_000 or hashlib.sha256(archive).hexdigest() != checksum:
        raise RuntimeError("Mihomo download checksum mismatch")
    BINARY.parent.mkdir(exist_ok=True)
    temporary = BINARY.with_suffix(".tmp")
    temporary.write_bytes(gzip.decompress(archive))
    temporary.chmod(0o700)
    temporary.replace(BINARY)


def private_config(encoded):
    try:
        incoming = json.loads(base64.b64decode(encoded, validate=True))
        proxies = incoming["proxies"]
        if not isinstance(proxies, list) or len(proxies) != 1 or not isinstance(proxies[0], dict):
            raise ValueError()
        node = dict(proxies[0])
        if node.get("type") not in {"trojan", "vmess", "vless", "ss", "socks5", "http"} or not node.get("server"):
            raise ValueError()
        if node.get("skip-cert-verify") and os.environ.get("MIHOMO_ALLOW_INSECURE_TLS") != "true":
            raise ValueError()
        node["name"] = "upstream"
        node["udp"] = False
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid private Mihomo configuration or unapproved TLS setting") from None
    # Only this loopback port is available; no TUN, controller, subscription,
    # dashboard, inbound listener, provider URL or user-supplied rules are used.
    return {"mixed-port": PORT, "allow-lan": False, "bind-address": "127.0.0.1",
            "mode": "rule", "log-level": "silent", "ipv6": False,
            "external-controller": "", "tun": {"enable": False},
            "dns": {"enable": False}, "geo-auto-update": False,
            "proxies": [node], "rules": ["MATCH,upstream"]}
