"""Render build: Python dependencies and checksum-pinned official Mihomo."""
import subprocess
import sys
from mihomo_runtime import install

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements-cloud.txt"], check=True)
    install()
    print("Verified Mihomo runtime installed")
