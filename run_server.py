"""Point d'entrée du connecteur, lançable depuis n'importe quel dossier."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bambu_mcp.server import main  # noqa: E402

main()
