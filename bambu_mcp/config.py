"""Chemins Bambu Studio et configuration locale du connecteur (config.json)."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"

# Imprimante cible de tous les slices, et process de départ compatible (les presets P1S réutilisent ceux de la X1C).
DEFAULT_MACHINE = "Bambu Lab P1S 0.4 nozzle"
DEFAULT_PROCESS = "0.20mm Standard @BBL X1C"


def load() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    return {}


def default_machine() -> str:
    return load().get("default_machine") or DEFAULT_MACHINE


def default_process() -> str:
    return load().get("default_process") or DEFAULT_PROCESS


def install_dir() -> Path:
    custom = load().get("bambu_studio_dir")
    if custom:
        return Path(custom)
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Bambu Studio"


def executable() -> Path:
    return install_dir() / "bambu-studio.exe"


def system_profiles_dir() -> Path:
    return install_dir() / "resources" / "profiles" / "BBL"


def data_dir() -> Path:
    custom = load().get("bambu_data_dir")
    if custom:
        return Path(custom)
    return Path(os.environ["APPDATA"]) / "BambuStudio"


def user_id() -> str | None:
    custom = load().get("user_id")
    if custom:
        return str(custom)
    user_root = data_dir() / "user"
    if not user_root.is_dir():
        return None
    # Le dossier numérique est le compte Bambu connecté ; "default" sert hors connexion.
    numeric = sorted(p.name for p in user_root.iterdir() if p.is_dir() and p.name.isdigit())
    if numeric:
        return numeric[0]
    return "default" if (user_root / "default").is_dir() else None


def user_presets_dir() -> Path | None:
    uid = user_id()
    return data_dir() / "user" / uid if uid else None


def output_dir() -> Path:
    d = Path(load().get("output_dir") or ROOT / "output")
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir() -> Path:
    d = ROOT / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def printer() -> dict:
    return load().get("printer", {})


def bambu_studio_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq bambu-studio.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return False
    return "bambu-studio.exe" in out.lower()
