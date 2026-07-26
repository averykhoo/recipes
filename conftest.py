"""Makes the repository root importable so `recipe_parser` resolves during tests."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
