import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir + forced demo mode, set before any `studio` import reads config.
_TMP = tempfile.mkdtemp(prefix="studio-test-")
os.environ["STUDIO_DATA_DIR"] = _TMP
os.environ["STUDIO_MOCK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
