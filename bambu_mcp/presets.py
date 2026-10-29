"""Bambu Studio presets: index of system and user profiles, inheritance, writing."""
import difflib
import json
import re
import shutil
import time
from functools import lru_cache
from pathlib import Path

from . import config

# Preset type -> key holding its name in the resolved config.
TYPES = {"process": "print_settings_id", "filament": "filament_settings_id", "machine": "printer_settings_id"}

# File structure keys, not print settings.
META_KEYS = {"inherits", "instantiation", "from", "setting_id", "base_id", "include", "type",
             "description", "renamed_from", "is_custom_defined", "version", "name"}


def _check_type(kind: str) -> None:
    if kind not in TYPES:
        raise ValueError(f"Unknown type {kind!r}: use process, filament or machine.")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=1)
def _system_index() -> dict:
    index = {k: {} for k in TYPES}
    base = config.system_profiles_dir()
    for kind in TYPES:
        for path in (base / kind).rglob("*.json"):
            try:
                data = _read_json(path)
            except (OSError, ValueError):
                continue
            index[kind][data.get("name") or path.stem] = (path, data)
    return index


_user_cache: dict = {"at": 0.0, "index": None}


def _user_index() -> dict:
    # Reread at most every 3 s: presets may change from Bambu Studio.
    if _user_cache["index"] is not None and time.monotonic() - _user_cache["at"] < 3:
        return _user_cache["index"]
    _user_cache["index"], _user_cache["at"] = _load_user_index(), time.monotonic()
    return _user_cache["index"]


def _load_user_index() -> dict:
    index = {k: {} for k in TYPES}
    udir = config.user_presets_dir()
    if not udir:
        return index
    for kind in TYPES:
        folder = udir / kind
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.json"):
            try:
                data = _read_json(path)
            except (OSError, ValueError):
                continue
            index[kind][data.get("name") or path.stem] = (path, data)
    return index


def find(kind: str, name: str) -> tuple[str, Path, dict]:
    """Return (source, path, raw content); user presets win."""
    _check_type(kind)
    users, systems = _user_index()[kind], _system_index()[kind]
    if name in users:
        return "user", *users[name]
    if name in systems:
        return "system", *systems[name]
    lowered = {n.lower(): n for n in list(users) + list(systems)}
    if name.lower() in lowered:
        return find(kind, lowered[name.lower()])
    close = difflib.get_close_matches(name, list(users) + list(systems), n=5, cutoff=0.5)
    hint = f" Close names: {close}" if close else ""
    raise KeyError(f"{kind.capitalize()} preset not found: {name!r}.{hint}")


def resolve(kind: str, name: str, _depth: int = 0) -> dict:
    """Complete config of a preset, with inheritance and includes applied."""
    if _depth > 20:
        raise RecursionError(f"Inheritance too deep for {name!r}")
    source, _, data = find(kind, name)
    if source == "system":
        return dict(_resolve_system(kind, name))
    out: dict = {}
    if data.get("inherits"):
        out.update(resolve(kind, data["inherits"], _depth + 1))
    for inc in data.get("include", []) or []:
        out.update(resolve(kind, inc, _depth + 1))
    out.update({k: v for k, v in data.items() if k not in META_KEYS})
    return out


@lru_cache(maxsize=4096)
def _resolve_system(kind: str, name: str) -> dict:
    data = _system_index()[kind][name][1]
    out: dict = {}
    if data.get("inherits"):
        out.update(_resolve_system(kind, data["inherits"]))
    for inc in data.get("include", []) or []:
        out.update(_resolve_system(kind, inc))
    out.update({k: v for k, v in data.items() if k not in META_KEYS})
    return out


def overrides(kind: str, name: str) -> dict:
    """Settings defined in the preset itself (inherited ones excluded)."""
    _, _, data = find(kind, name)
    return {k: v for k, v in data.items() if k not in META_KEYS}


def system_parent(kind: str, name: str) -> str | None:
    """First system ancestor of a preset (itself if it is a system preset)."""
    source, _, data = find(kind, name)
    if source == "system":
        return name
    parent = data.get("inherits")
    return system_parent(kind, parent) if parent else None


def is_compatible(kind: str, name: str, printer: str) -> bool:
    if kind == "machine":
        return True
    compat = resolve(kind, name).get("compatible_printers") or []
    return not compat or printer in compat


def canonical(kind: str, name: str) -> str:
    """Exact name of a preset (lookup tolerates case differences)."""
    _, _, data = find(kind, name)
    return data.get("name") or name


def standard_process(machine: str) -> str:
    """The printer's "0.20mm Standard" process (fallback: its first system process)."""
    names = [r["name"] for r in list_presets("process", "system", machine)]
    if not names:
        raise KeyError(f"No system process compatible with {machine!r}.")
    return next((n for n in names if n.startswith("0.20mm Standard")), names[0])


def for_machine(kind: str, name: str, machine: str) -> str:
    """Variant of a system preset for `machine`: "Bambu PLA Basic @BBL P1S 0.4 nozzle" becomes
    "Bambu PLA Basic @BBL A1" on an A1. A preset that is already compatible is returned as is."""
    name = canonical(kind, name)
    if is_compatible(kind, name, machine):
        return name
    base = name.split(" @")[0]
    match = next((r["name"] for r in list_presets(kind, "system", machine, base)
                  if r["name"].split(" @")[0] == base), None)
    if not match:
        raise KeyError(f"No version of {name!r} for {machine!r}.")
    return match


def list_presets(kind: str, source: str = "all", printer: str | None = None,
                 search: str | None = None) -> list[dict]:
    _check_type(kind)
    rows = []
    if source in ("all", "user"):
        for name, (path, data) in _user_index()[kind].items():
            rows.append({"name": name, "source": "user", "inherits": data.get("inherits", ""),
                         "overrides": len([k for k in data if k not in META_KEYS])})
    if source in ("all", "system"):
        for name, (path, data) in _system_index()[kind].items():
            if str(data.get("instantiation", "")).lower() != "true":
                continue  # Internal base profiles, never offered in the UI.
            rows.append({"name": name, "source": "system", "inherits": data.get("inherits", "")})
    if search:
        words = search.lower().split()
        rows = [r for r in rows if all(w in r["name"].lower() for w in words)]
    if printer:
        kept = []
        for r in rows:
            try:
                if is_compatible(kind, r["name"], printer):
                    kept.append(r)
            except (KeyError, RecursionError):
                continue
        rows = kept
    return sorted(rows, key=lambda r: (r["source"] != "user", r["name"].lower()))


def _to_str(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def normalize(current, value):
    """Put a value in Bambu format: string, or list of strings as long as the existing one."""
    if isinstance(current, list):
        if isinstance(value, list):
            return [_to_str(v) for v in value]
        return [_to_str(value)] * max(1, len(current))
    if isinstance(value, list):
        raise ValueError(f"list given for a single-value setting (current value {current!r})")
    return _to_str(value)


@lru_cache(maxsize=None)
def _profile_keys(kind: str) -> frozenset:
    return frozenset(k for _, data in _system_index()[kind].values() for k in data if k not in META_KEYS)


@lru_cache(maxsize=None)
def known_keys(kind: str) -> frozenset:
    """Valid settings for a type. A preset does not write settings left at their default value
    (brim_type…): those come from settings_keys.json, the complete list of a project exported by
    Bambu Studio, filed on the filament side if they start with filament_, otherwise on the process side."""
    _check_type(kind)
    own = _profile_keys(kind)
    if kind == "machine":
        return own
    others = _profile_keys("machine") | _profile_keys("filament" if kind == "process" else "process")
    extra = {k for k in json.loads((Path(__file__).parent / "settings_keys.json").read_text(encoding="utf-8"))
             if k not in others and k not in own}
    side = {k for k in extra if k.startswith("filament_") == (kind == "filament")}
    return own | side


def apply_settings(base: dict, settings: dict, allow_new_keys: bool = False,
                   known: frozenset | None = None) -> tuple[dict, list]:
    """Normalize `settings` against `base`. Return (normalized settings, changes).
    `known`: keys accepted even when missing from `base`."""
    unknown = [k for k in settings if k not in base and not allow_new_keys and k not in (known or ())]
    if unknown:
        suggestions = {k: difflib.get_close_matches(k, list(base), n=3, cutoff=0.6) for k in unknown}
        raise KeyError(f"Unknown settings: {suggestions}")
    normalized, changes = {}, []
    for key, value in settings.items():
        new = normalize(base.get(key, ""), value)
        normalized[key] = new
        if base.get(key) != new:
            changes.append({"key": key, "before": base.get(key), "after": new})
    return normalized, changes


def _safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def _backup(paths: list[Path]) -> Path:
    dest = config.backup_dir() / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if p.exists():
            shutil.copy2(p, dest / p.name)
    return dest


def _write_info(info_path: Path, base_id: str) -> None:
    fields = {"sync_info": "", "user_id": config.user_id() or "", "setting_id": "",
              "base_id": base_id, "updated_time": str(int(time.time()))}
    if info_path.exists():
        for line in info_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line:
                k, v = (s.strip() for s in line.split("=", 1))
                fields[k] = v
        fields["updated_time"] = str(int(time.time()))
    info_path.write_text("".join(f"{k} = {v}\n" for k, v in fields.items()), encoding="utf-8")


def save_user_preset(kind: str, name: str, settings: dict, parent: str | None = None) -> dict:
    """Create or update a user preset. Backs up the old file before writing."""
    _check_type(kind)
    udir = config.user_presets_dir()
    if not udir:
        raise FileNotFoundError("Bambu Studio user folder not found.")
    users = _user_index()[kind]
    backup = None
    if name in users:
        path, own = users[name]
        own = dict(own)
        backup = _backup([path, path.with_suffix(".info")])
        created = False
    else:
        if not parent:
            raise ValueError("New preset: give `parent` (system or user preset).")
        psource, _, pdata = find(kind, parent)
        if psource == "user":
            # Bambu Studio only accepts a system parent: the user parent's overrides are copied over.
            own = {k: v for k, v in pdata.items() if k not in META_KEYS}
            own["inherits"] = pdata.get("inherits", "")
            own["version"] = pdata.get("version", "")
        else:
            own = {"inherits": parent, "version": pdata.get("version", "")}
        path = udir / kind / f"{_safe_filename(name)}.json"
        created = True
    current = resolve(kind, own["inherits"]) if own.get("inherits") else {}
    current.update({k: v for k, v in own.items() if k not in META_KEYS})
    normalized, changes = apply_settings(current, settings)
    own.update(normalized)
    own["name"] = name
    own["from"] = "User"
    id_key = TYPES[kind]
    own[id_key] = [name] if isinstance(current.get(id_key), list) else name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(own.items())), indent=4, ensure_ascii=False), encoding="utf-8")
    base_id = ""
    if own.get("inherits"):
        base_id = find(kind, own["inherits"])[2].get("setting_id", "")
    _write_info(path.with_suffix(".info"), base_id)
    _user_cache["index"] = None
    return {"name": name, "file": str(path), "created": created, "inherits": own.get("inherits"),
            "changes": changes, "backup": str(backup) if backup else None,
            "bambu_studio_running": config.bambu_studio_running()}


def diff(kind: str, a: str, b: str) -> list[dict]:
    ra, rb = resolve(kind, a), resolve(kind, b)
    keys = sorted(set(ra) | set(rb))
    return [{"key": k, a: ra.get(k), b: rb.get(k)} for k in keys if ra.get(k) != rb.get(k)]
