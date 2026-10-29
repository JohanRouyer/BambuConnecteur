"""Lecture et modification des projets 3MF de Bambu Studio."""
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import presets

MODEL = "3D/3dmodel.model"
PROJECT = "Metadata/project_settings.config"
MODEL_SETTINGS = "Metadata/model_settings.config"
SLICE_INFO = "Metadata/slice_info.config"

# Métadonnées d'objet qui ne sont pas des réglages d'impression.
OBJECT_META = {"name", "extruder", "matrix", "source_file", "source_object_id", "source_volume_id",
               "source_offset_x", "source_offset_y", "source_offset_z"}


def _application(model_xml: str) -> str | None:
    m = re.search(r'<metadata name="Application"[^>]*>([^<]*)</metadata>', model_xml)
    return m.group(1) if m else None


def _parse_model_settings(raw: bytes) -> tuple[list, list]:
    root = ET.fromstring(raw)
    objects = []
    for obj in root.findall("object"):
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("key")}
        parts = []
        for part in obj.findall("part"):
            pmeta = {m.get("key"): m.get("value") for m in part.findall("metadata") if m.get("key")}
            parts.append({"id": part.get("id"), "name": pmeta.get("name"), "subtype": part.get("subtype"),
                          "overrides": {k: v for k, v in pmeta.items() if k not in OBJECT_META}})
        objects.append({"id": obj.get("id"), "name": meta.get("name"), "extruder": meta.get("extruder"),
                        "overrides": {k: v for k, v in meta.items() if k not in OBJECT_META},
                        "parts": parts})
    plates = []
    for plate in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata") if m.get("key")}
        instances = []
        for inst in plate.findall("model_instance"):
            imeta = {m.get("key"): m.get("value") for m in inst.findall("metadata") if m.get("key")}
            instances.append(imeta.get("object_id"))
        plates.append({"id": meta.get("plater_id"), "name": meta.get("plater_name"),
                       "object_ids": instances, "has_gcode": bool(meta.get("gcode_file"))})
    return objects, plates


def parse_slice_info(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    plates = []
    for plate in root.findall("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata") if m.get("key")}
        if "prediction" not in meta:
            continue
        seconds = int(float(meta.get("prediction") or 0))
        filaments = [{k: f.get(k) for k in ("id", "type", "color", "used_m", "used_g")}
                     for f in plate.findall("filament")]
        warnings = [{k: w.get(k) for k in ("msg", "level", "error_code")} for w in plate.findall("warning")]
        plates.append({"plate": meta.get("index"), "time_s": seconds,
                       "time": f"{seconds // 3600}h{(seconds % 3600) // 60:02d}",
                       "weight_g": meta.get("weight"), "support_used": meta.get("support_used"),
                       "filaments": filaments, "warnings": warnings})
    return plates


def inspect(path: str) -> dict:
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        model_xml = z.read(MODEL).decode("utf-8", "replace") if MODEL in names else ""
        app = _application(model_xml)
        info = {"file": str(p), "application": app,
                "bambu_project": bool(app and ("BambuStudio" in app or "OrcaSlicer" in app)),
                "has_project_settings": PROJECT in names,
                "has_sliced_gcode": any(n.endswith(".gcode") for n in names)}
        if PROJECT in names:
            ps = json.loads(z.read(PROJECT))
            keys = ["printer_settings_id", "print_settings_id", "filament_settings_id", "layer_height",
                    "wall_loops", "sparse_infill_density", "sparse_infill_pattern", "enable_support",
                    "support_type", "brim_type", "curr_bed_type", "filament_type", "nozzle_temperature"]
            info["settings_summary"] = {k: ps.get(k) for k in keys if k in ps}
            info["modified_vs_presets"] = ps.get("different_settings_to_system")
        if MODEL_SETTINGS in names:
            info["objects"], info["plates"] = _parse_model_settings(z.read(MODEL_SETTINGS))
        if SLICE_INFO in names:
            info["slice_results"] = parse_slice_info(z.read(SLICE_INFO))
    if not info["has_project_settings"]:
        info["note"] = ("Fichier sans réglages Bambu : seule la géométrie sera chargée. "
                        "Utiliser export_bambu_project pour lui appliquer des presets.")
    return info


def get_settings(path: str, key_filter: str | None = None) -> dict:
    with zipfile.ZipFile(path) as z:
        if PROJECT not in z.namelist():
            raise ValueError("Ce 3MF ne contient pas de réglages Bambu (project_settings.config).")
        ps = json.loads(z.read(PROJECT))
    if key_filter:
        words = key_filter.lower().split()
        ps = {k: v for k, v in ps.items() if any(w in k.lower() for w in words)}
    return ps


def _key_kind(ps: dict, key: str) -> str | None:
    """Indique à quel preset (process / filament / machine) appartient une clé du projet."""
    for kind, id_key in presets.TYPES.items():
        name = ps.get(id_key)
        if isinstance(name, list):
            name = name[0] if name else None
        if not name:
            continue
        try:
            if key in presets.resolve(kind, name):
                return kind
        except (KeyError, RecursionError):
            continue
    return None


def _mark_modified(ps: dict, keys: list[str]) -> None:
    """Ajoute les clés modifiées à different_settings_to_system (process, filaments..., machine)."""
    diffs = ps.get("different_settings_to_system")
    if not isinstance(diffs, list) or len(diffs) < 2:
        return
    for key in keys:
        kind = _key_kind(ps, key)
        slots = {"process": [0], "machine": [len(diffs) - 1],
                 "filament": list(range(1, len(diffs) - 1))}.get(kind, [])
        for i in slots:
            current = [k for k in diffs[i].split(";") if k]
            if key not in current:
                diffs[i] = ";".join(current + [key])


def _set_object_settings(raw: bytes, object_settings: dict, ps: dict) -> tuple[bytes, list]:
    root = ET.fromstring(raw)
    changes = []
    objects = root.findall("object")
    for target, settings in object_settings.items():
        matches = [o for o in objects if o.get("id") == str(target)
                   or any(m.get("key") == "name" and m.get("value") == target for m in o.findall("metadata"))]
        if not matches:
            names = [m.get("value") for o in objects for m in o.findall("metadata") if m.get("key") == "name"]
            raise KeyError(f"Objet introuvable : {target!r}. Objets : {names}")
        for obj in matches:
            for key, value in settings.items():
                if key not in ps:
                    raise KeyError(f"Réglage inconnu pour l'objet {target!r} : {key!r}")
                # Les surcharges d'objet sont toujours des valeurs simples.
                ref = ps[key][0] if isinstance(ps[key], list) and ps[key] else ps[key]
                new = presets.normalize(ref, value)
                existing = next((m for m in obj.findall("metadata") if m.get("key") == key), None)
                before = existing.get("value") if existing is not None else None
                if existing is None:
                    existing = ET.Element("metadata", {"key": key, "value": new})
                    # Après les métadonnées existantes, avant les <part>.
                    index = len(obj.findall("metadata"))
                    obj.insert(index, existing)
                existing.set("value", new)
                changes.append({"object": target, "key": key, "before": before, "after": new})
    ET.indent(root, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8"), changes


def is_project(path: str) -> bool:
    """Vrai pour un 3MF qui porte ses propres réglages Bambu (project_settings.config)."""
    if Path(path).suffix.lower() != ".3mf":
        return False
    with zipfile.ZipFile(path) as z:
        return PROJECT in z.namelist()


def _set_machine(ps: dict, machine: str) -> dict | None:
    """Remplace la partie imprimante du projet par le preset `machine`, process et filaments gardés.
    Rien à faire si le projet vise déjà ce modèle (preset utilisateur dérivé compris)."""
    cfg = presets.resolve("machine", machine)
    if ps.get("printer_model") == cfg.get("printer_model"):
        return None
    before = ps.get("printer_settings_id")
    ps.update(cfg)
    ps["printer_settings_id"] = machine
    diffs = ps.get("different_settings_to_system")
    if isinstance(diffs, list) and diffs:
        diffs[-1] = ""  # Dernier emplacement : écarts au preset machine, qui n'existent plus.
    return {"key": "printer_settings_id", "before": before, "after": machine}


def edit(path: str, settings: dict | None = None, object_settings: dict | None = None,
         output_path: str | None = None, machine: str | None = None) -> dict:
    """Écrit une copie modifiée du 3MF. L'original n'est remplacé que si output_path == path.
    `machine` : convertit le projet vers ce preset imprimante avant d'appliquer `settings`."""
    src = Path(path)
    out = Path(output_path) if output_path else src.with_name(f"{src.stem}_claude{src.suffix}")
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        if PROJECT not in names:
            raise ValueError("Pas de réglages Bambu dans ce 3MF : utiliser export_bambu_project d'abord.")
        ps = json.loads(z.read(PROJECT))
        changes: list = []
        converted = _set_machine(ps, machine) if machine else None
        if converted:
            changes.append(converted)
        if settings:
            normalized, setting_changes = presets.apply_settings(ps, settings)
            changes += setting_changes
            ps.update(normalized)
            _mark_modified(ps, list(normalized))
        replaced = {PROJECT: json.dumps(ps, indent=4, ensure_ascii=False).encode("utf-8")}
        object_changes: list = []
        if object_settings:
            if MODEL_SETTINGS not in names:
                raise ValueError("Pas de model_settings.config : réglages par objet impossibles.")
            replaced[MODEL_SETTINGS], object_changes = _set_object_settings(
                z.read(MODEL_SETTINGS), object_settings, ps)
        tmp = out.with_suffix(out.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as w:
            for item in z.infolist():
                data = replaced.get(item.filename)
                w.writestr(item, data if data is not None else z.read(item.filename))
    if out.resolve() == src.resolve():
        shutil.copy2(src, src.with_name(f"{src.stem}.backup{src.suffix}"))
    tmp.replace(out)
    result = {"output": str(out), "changes": changes, "object_changes": object_changes}
    if any(n.endswith(".gcode") for n in names):
        result["warning"] = "Le G-code déjà présent dans ce fichier est obsolète : re-slicer avant d'imprimer."
    return result
