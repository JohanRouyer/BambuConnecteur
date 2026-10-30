"""Bambu Studio paths and the connector's local configuration (config.json)."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Where config.json, output\ and backups\ live. The Claude plugin points it at its data folder,
# which survives plugin updates; a plain clone keeps everything in the project folder.
HOME = Path(os.environ.get("BAMBU_ADVISOR_HOME") or ROOT)
CONFIG_FILE = HOME / "config.json"

# Fallback target printer and a compatible starting process (P1S presets reuse the X1C processes).
DEFAULT_MACHINE = "Bambu Lab P1S 0.4 nozzle"
DEFAULT_PROCESS = "0.20mm Standard @BBL X1C"


def load() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    return {}


def save(updates: dict) -> None:
    """Merge `updates` into config.json (other keys, `printer` included, are kept)."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({**load(), **updates}, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def setup_needed() -> bool:
    """First use: the default printer has not been chosen yet."""
    return not load().get("default_machine")


def default_machine() -> str:
    return load().get("default_machine") or DEFAULT_MACHINE


def default_process() -> str:
    return load().get("default_process") or DEFAULT_PROCESS


def default_filament() -> str | None:
    return load().get("default_filament")


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
    # The numeric folder is the signed-in Bambu account; "default" is used offline.
    numeric = sorted(p.name for p in user_root.iterdir() if p.is_dir() and p.name.isdigit())
    if numeric:
        return numeric[0]
    return "default" if (user_root / "default").is_dir() else None


def user_presets_dir() -> Path | None:
    uid = user_id()
    return data_dir() / "user" / uid if uid else None


def output_dir() -> Path:
    d = Path(load().get("output_dir") or HOME / "output")
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir() -> Path:
    d = HOME / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Printer connection given through the environment (the plugin's settings), over config.json.
PRINTER_ENV = {"host": "BAMBU_PRINTER_HOST", "serial": "BAMBU_PRINTER_SERIAL", "access_code": "BAMBU_PRINTER_ACCESS_CODE"}


def printer() -> dict:
    cfg = dict(load().get("printer", {}))
    for key, var in PRINTER_ENV.items():
        value = os.environ.get(var, "").strip()
        if value and not value.startswith("${"):  # An unset plugin setting may arrive unsubstituted.
            cfg[key] = value
    return cfg


def bambu_studio_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq bambu-studio.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return False
    return "bambu-studio.exe" in out.lower()
