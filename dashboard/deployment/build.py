"""Render build: Python dependencies and checksum-pinned official Mihomo."""
import subprocess
import sys
from deployment.mihomo_runtime import install

def main():
    from backend.paths import DASHBOARD_ROOT
    import os
    os.chdir(DASHBOARD_ROOT)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements-cloud.txt"], check=True)
    install()
    print("Verified Mihomo runtime installed")


if __name__ == "__main__":
    main()
