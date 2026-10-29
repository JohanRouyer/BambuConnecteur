"""Connector entry point, runnable from any folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bambu_mcp.server import main  # noqa: E402

main()
