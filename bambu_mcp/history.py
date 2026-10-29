"""Slice history: one JSON line per slice in output/history.jsonl."""
import json
import threading
import time

from . import config

_lock = threading.Lock()  # compare_slices writes from several threads


def duration(seconds: int) -> str:
    """Duration in Bambu Studio format: 1h05."""
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


def _file():
    return config.output_dir() / "history.jsonl"


def record(models: list, summary: dict, machine: str | None, process: str | None,
           filaments: list | None, overrides: dict, label: str | None) -> None:
    plates = summary.get("plates") or []
    seconds = sum(p["time_s"] for p in plates)
    entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "models": [str(m) for m in models], "label": label,
             "machine": machine, "process": process, "filaments": filaments, "overrides": overrides,
             "ok": summary.get("return_code") == 0, "time_s": seconds,
             "time": duration(seconds),
             "weight_g": round(sum(p["filament_g"] for p in plates), 2), "plates": len(plates),
             "checks": len(summary.get("checks") or []), "cached": summary.get("cached", False),
             "project_3mf": summary.get("project_3mf")}
    with _lock, _file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read(limit: int = 20, search: str | None = None) -> list[dict]:
    """Latest slices, newest first; `search` filters on model names and the label."""
    path = _file()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if search:
        words = search.lower().split()
        rows = [r for r in rows if all(w in (" ".join(r["models"]) + " " + (r.get("label") or "")).lower()
                                       for w in words)]
    return rows[::-1][:limit]
