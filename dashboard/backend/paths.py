"""Stable paths, independent of process working directory and module location."""
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = DASHBOARD_ROOT / "frontend"
CACHE_ROOT = DASHBOARD_ROOT / ".cache"
