"""Ensure the repo root is importable so `import backend.*` works regardless of
the pytest invocation directory."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../SplatAgent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
