"""Central path definitions. The ground-truth folder is deliberately NOT defined
here, so modules importing `common` cannot reach it by accident."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
REFERENCE = DATA / "reference"
GENERATED = DATA / "generated"
OUTPUTS = ROOT / "outputs"
SQLITE_URL = f"sqlite:///{GENERATED / 'core_banking.sqlite'}"
