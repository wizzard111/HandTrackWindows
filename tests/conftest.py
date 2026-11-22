import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
# Never touch the real user folder from tests.
os.environ.setdefault("HANDTRACK_DATA_DIR", tempfile.mkdtemp(prefix="handtrack-test-"))
