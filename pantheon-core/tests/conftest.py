import os
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

os.environ.setdefault("PANTHEON_HARNESS_DIR", str(FIXTURES_DIR / "harnesses"))
os.environ.setdefault("PANTHEON_SANCTUARIES_DIR", str(FIXTURES_DIR / "sanctuaries"))
