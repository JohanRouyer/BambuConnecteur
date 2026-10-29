"""Préparation complète d'une impression P1S : STL ou 3MF + matériau + objectif -> projet slicé."""
import shutil
import tempfile
from pathlib import Path

from . import config, geometry, history, materials, presets, slicer


def prepare(models: list[str], material: str = "PLA", goal: str = "equilibre", copies: int = 1,
            orientation: str = "auto", supports: str = "auto", bed_type: str | None = None,
            filament: str | None = None, extra_settings: dict | None = None) -> dict:
    """Analyse, oriente, choisit presets / plateau / supports / bordure, puis slice."""
    if goal not in slicer.GOALS:
        raise ValueError(f"Objectif inconnu {goal!r} : {list(slicer.GOALS)}")
    if orientation not in ("auto", "as_is"):
        raise ValueError("orientation : 'auto' ou 'as_is'.")
    if supports not in ("auto", "on", "off"):
        raise ValueError("supports : 'auto', 'on' ou 'off'.")
    if not 1 <= copies <= 50:
        raise ValueError("copies : entre 1 et 50.")
    mat_name, mat = materials.find(material)
    guide = materials.guide(mat_name, filament)
    filament = guide["filament_preset"]
    decisions = [f"Matériau {mat_name} : preset {filament}."]

    work = Path(tempfile.mkdtemp(prefix="bmcp_prep_"))
    try:
        inputs, analyses, needs_support, needs_brim, orient_3mf = [], [], False, bool(mat.get("brim")), False
        for model in models:
            path = Path(model)
            a = geometry.analyze(str(path))
            chosen = a["current"]
            if orientation == "auto" and a["best_orientation"] != chosen["orientation"]:
                chosen = next(r for r in a["orientations"] if r["orientation"] == a["best_orientation"])
                if path.suffix.lower() == ".stl":
                    path = geometry.write_rotated_stl(str(path), chosen["rotate_x"], chosen["rotate_y"],
                                                      work / path.name)
                else:
                    orient_3mf = True
                decisions.append(f"{Path(model).name} : {chosen['orientation']} "
                                 f"(surplombs {a['current']['overhang_pct']} % → {chosen['overhang_pct']} %).")
            if not chosen["fits_p1s"]:
                raise ValueError(f"{Path(model).name} ne tient pas sur la P1S ({chosen['size_mm']} mm, "
                                 "max 256 x 256 x 250) : réduire l'échelle ou découper.")
            needs_support |= chosen["needs_support"]
            w, d, h = chosen["size_mm"]
            needs_brim |= chosen["base_area_mm2"] < 50 or (min(w, d) > 0 and h / min(w, d) > 4)
            analyses.append({"model": Path(model).name, "orientation": chosen["orientation"],
                             "size_mm": chosen["size_mm"], "overhang_pct": chosen["overhang_pct"],
                             "needs_support": chosen["needs_support"], "volume_cm3": a["volume_cm3"]})
            if copies > 1 and path.suffix.lower() == ".3mf":
                raise ValueError("copies > 1 : seulement avec des STL (dupliquer les objets dans Bambu Studio pour un 3MF).")
            inputs += [str(path)] * copies

        settings = dict(slicer.GOALS[goal])
        if supports == "on" or (supports == "auto" and needs_support):
            settings.update({"enable_support": "1", "support_type": "tree(auto)"})
            decisions.append("Supports arborescents activés" + (" (surplombs détectés)." if supports == "auto" else "."))
        else:
            settings["enable_support"] = "0"
        if needs_brim:
            settings.update({"brim_type": "outer_only", "brim_width": "5"})
            decisions.append("Bordure de 5 mm (" + ("matériau qui se rétracte" if mat.get("brim")
                                                      else "petite assise ou pièce haute") + ").")
        settings.update(extra_settings or {})

        plate = bed_type or next((p for p in mat["plate"] if (guide["bed_c"].get(p) or "0") != "0"), None)
        decisions.append(f"Plateau : {plate} ({guide['bed_c'].get(plate)} °C).")
        machine, process = config.default_machine(), config.default_process()
        proc, fil = slicer._split(settings, machine, process, [filament])
        result = slicer.run(inputs, machine, process, [filament], proc, fil or None, 0, plate,
                            orient=orient_3mf, arrange=len(inputs) > 1 or any(i.lower().endswith(".stl") for i in inputs),
                            label=f"{mat_name}_{goal}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    warnings = []
    nozzle = presets.resolve("machine", config.default_machine()).get("nozzle_type")
    nozzle = nozzle[0] if isinstance(nozzle, list) else nozzle
    if mat.get("abrasive") and nozzle != "hardened_steel":
        warnings.append(f"{mat_name} est abrasif et le preset machine indique une buse {nozzle} : "
                        "monter une buse en acier trempé (et la déclarer dans Bambu Studio).")
    plates = result.get("plates") or []
    seconds = sum(p["time_s"] for p in plates)
    return {"ok": result.get("return_code") == 0, "message": result.get("message"),
            "time": history.duration(seconds), "weight_g": round(sum(p["filament_g"] for p in plates), 2),
            "plates": len(plates), "project_3mf": result.get("project_3mf"), "decisions": decisions,
            "warnings": warnings + [p["warning"] for p in plates if p.get("warning")] + result.get("checks", []),
            "models": analyses, "material": {k: guide[k] for k in ("enclosure", "ams_ok", "nozzle_c", "notes")},
            "settings": settings, "cached": result.get("cached", False),
            **({"stderr": result["stderr"]} if "stderr" in result else {})}
