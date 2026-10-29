"""Presets Bambu Studio : index des profils système et utilisateur, héritage, écriture."""
import difflib
import json
import re
import shutil
import time
from functools import lru_cache
from pathlib import Path

from . import config

# Type de preset -> clé qui porte son nom dans la config résolue.
TYPES = {"process": "print_settings_id", "filament": "filament_settings_id", "machine": "printer_settings_id"}

# Clés de structure du fichier, pas des réglages d'impression.
META_KEYS = {"inherits", "instantiation", "from", "setting_id", "base_id", "include", "type",
             "description", "renamed_from", "is_custom_defined", "version", "name"}


def _check_type(kind: str) -> None:
    if kind not in TYPES:
        raise ValueError(f"Type inconnu {kind!r} : utiliser process, filament ou machine.")


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
    # Relu au plus toutes les 3 s : les presets peuvent changer depuis Bambu Studio.
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
    """Renvoie (source, chemin, contenu brut) ; les presets utilisateur priment."""
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
    hint = f" Noms proches : {close}" if close else ""
    raise KeyError(f"Preset {kind} introuvable : {name!r}.{hint}")


def resolve(kind: str, name: str, _depth: int = 0) -> dict:
    """Config complète d'un preset, héritage et includes appliqués."""
    if _depth > 20:
        raise RecursionError(f"Héritage trop profond pour {name!r}")
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
    """Réglages définis dans le preset lui-même (sans ceux hérités)."""
    _, _, data = find(kind, name)
    return {k: v for k, v in data.items() if k not in META_KEYS}


def system_parent(kind: str, name: str) -> str | None:
    """Premier ancêtre système d'un preset (lui-même s'il est système)."""
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
                continue  # Profils de base internes, jamais proposés dans l'interface.
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
    """Met une valeur au format Bambu : chaîne, ou liste de chaînes de même longueur que l'existante."""
    if isinstance(current, list):
        if isinstance(value, list):
            return [_to_str(v) for v in value]
        return [_to_str(value)] * max(1, len(current))
    if isinstance(value, list):
        raise ValueError(f"liste reçue pour un réglage simple (valeur actuelle {current!r})")
    return _to_str(value)


def apply_settings(base: dict, settings: dict, allow_new_keys: bool = False) -> tuple[dict, list]:
    """Normalise `settings` par rapport à `base`. Renvoie (réglages normalisés, changements)."""
    unknown = [k for k in settings if k not in base and not allow_new_keys]
    if unknown:
        suggestions = {k: difflib.get_close_matches(k, list(base), n=3, cutoff=0.6) for k in unknown}
        raise KeyError(f"Réglages inconnus : {suggestions}")
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
    """Crée ou met à jour un preset utilisateur. Sauvegarde l'ancien fichier avant d'écrire."""
    _check_type(kind)
    udir = config.user_presets_dir()
    if not udir:
        raise FileNotFoundError("Dossier utilisateur Bambu Studio introuvable.")
    users = _user_index()[kind]
    backup = None
    if name in users:
        path, own = users[name]
        own = dict(own)
        backup = _backup([path, path.with_suffix(".info")])
        created = False
    else:
        if not parent:
            raise ValueError("Nouveau preset : indiquer `parent` (preset système ou utilisateur).")
        psource, _, pdata = find(kind, parent)
        if psource == "user":
            # Bambu Studio n'accepte qu'un parent système : on recopie les surcharges du parent utilisateur.
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
