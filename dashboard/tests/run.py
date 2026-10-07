"""Run all backend and frontend regression checks from any working directory."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

def main():
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests/backend'), '-p', 'test_*.py'], cwd=REPO, env=env, check=True)
    for test in sorted((ROOT / 'tests/frontend').glob('test_*.cjs')):
        subprocess.run(['node', str(test)], cwd=REPO, check=True)
    subprocess.run(['node', str(REPO / 'frontend/build.cjs')], cwd=REPO, check=True)

if __name__ == '__main__':
    main()
