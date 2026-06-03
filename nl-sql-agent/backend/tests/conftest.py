import sys
from pathlib import Path

# Ensure the backend root is on the path so `mcp_server` and `agent` are importable
sys.path.insert(0, str(Path(__file__).parent.parent))
