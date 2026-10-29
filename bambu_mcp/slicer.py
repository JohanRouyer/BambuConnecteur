"""Slicing et export de projets via la ligne de commande de Bambu Studio."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import analysis, config, history, materials, presets, threemf


def _flatten(kind: str, name: str, overrides: dict | None, dest: Path) -> list:
    """Écrit le preset entièrement résolu : la CLI ne connaît pas les presets utilisateur."""
    cfg = presets.resolve(kind, name)
    changes = []
    if overrides:
        normalized, changes = presets.apply_settings(cfg, overrides, known=presets.known_keys(kind))
        cfg.update(normalized)
    cfg.update({"name": name, "type": kind, "from": "system", "inherits": "",
                "version": presets.find(kind, name)[2].get("version", "")})
    dest.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    return changes


def _default_presets(models: list[str], machine: str | None, process: str | None,
                     filaments: list[str] | None) -> tuple:
    """STL ou 3MF géométrie seule sans presets : imprimante, process et filament par défaut (PLA à défaut)."""
    if machine or all(threemf.is_project(m) for m in models):
        return machine, process, filaments
    machine = config.default_machine()
    return machine, config.default_process(), filaments or [
        config.default_filament() or presets.for_machine("filament", materials.MATERIALS["PLA"]["filament"], machine)]


def fit_machine(settings: dict, machine: str) -> dict:
    """Ramène les accélérations d'une recette à 75 % du maximum de l'imprimante (A1 : 12 000)."""
    limit = presets.resolve("machine", machine).get("machine_max_acceleration_extruding") or ["20000"]
    cap = int(float(limit[0] if isinstance(limit, list) else limit) * 0.75)
    return {k: (str(min(int(v), cap)) if k.endswith("_acceleration") and v.isdigit() else v)
            for k, v in settings.items()}


def _filament_slots(models: list[Path]) -> int:
    """Nombre de filaments déclarés par les projets 3MF (au moins 1)."""
    slots = 1
    for m in models:
        if threemf.is_project(str(m)):
            ids = threemf.get_settings(str(m), "filament_settings_id").get("filament_settings_id")
            slots = max(slots, len(ids) if isinstance(ids, list) else 1)
    return slots


def run(models: list[str], machine: str | None = None, process: str | None = None,
        filaments: list[str] | None = None, process_overrides: dict | None = None,
        filament_overrides: dict | None = None, plate: int = 0,
        bed_type: str | None = None, orient: bool = False, arrange: bool = False,
        label: str | None = None, timeout_s: int = 300) -> dict:
    """Lance bambu-studio.exe. Sans presets, un 3MF Bambu garde ses propres réglages, mais passe sur
    l'imprimante par défaut (P1S) s'il visait un autre modèle ; un STL reçoit les presets par défaut.
    `filaments` seul sur un projet : remplace son filament (le dernier nommé complète les emplacements),
    process du projet gardé. `plate` 0 : tous les plateaux, dans un seul result.3mf.
    Un slice identique déjà fait est renvoyé depuis le cache (`cached`: true)."""
    exe = config.executable()
    if not exe.exists():
        raise FileNotFoundError(f"Bambu Studio introuvable : {exe}")
    model_paths = [Path(m).resolve() for m in models]
    for m in model_paths:
        if not m.exists():
            raise FileNotFoundError(f"Modèle introuvable : {m}")
    if process and not machine:
        raise ValueError("Indiquer aussi `machine` quand on charge un preset process.")
    if machine and process_overrides and not process:
        raise ValueError("`process_overrides` avec `machine` demande aussi `process`.")
    if machine and filament_overrides and not filaments:
        raise ValueError("`filament_overrides` avec `machine` demande aussi `filaments`.")
    machine, process, filaments = _default_presets(models, machine, process, filaments)
    # Sans presets, les overrides s'appliquent aux réglages propres du projet 3MF,
    # converti au passage vers l'imprimante par défaut. Un filament chargé garde ses propres overrides.
    project_overrides = {} if machine else {**({} if filaments else filament_overrides or {}),
                                            **(process_overrides or {})}
    convert_to = None if machine else config.default_machine()
    if filaments and not machine:
        filaments = filaments + filaments[-1:] * (_filament_slots(model_paths) - len(filaments))

    # Dossier court : la CLI échoue quand le chemin de travail est trop long.
    work = Path(tempfile.mkdtemp(prefix="bmcp_"))
    args = [str(exe), "--debug", "1"]
    applied: dict = {}
    if machine:
        _flatten("machine", machine, None, work / "machine.json")
        settings_files = ["machine.json"]
        if process:
            applied["process"] = _flatten("process", process, process_overrides, work / "process.json")
            settings_files.append("process.json")
        args += ["--load-settings", ";".join(settings_files)]
    if filaments:
        names = []
        for i, name in enumerate(filaments, 1):
            applied[f"filament_{i}"] = _flatten("filament", name, filament_overrides, work / f"filament_{i}.json")
            names.append(f"filament_{i}.json")
        args += ["--load-filaments", ";".join(names)]
    # Toujours slicer : sans --slice, la CLI refuse d'exporter le 3MF (code -13).
    args += ["--slice", str(plate)]
    bed_type = bed_type or config.load().get("default_bed_type")
    if bed_type:
        args += ["--curr-bed-type", bed_type]
    if orient:
        args += ["--orient", "1"]
    if arrange:
        args += ["--arrange", "1"]
    # Les modèles aussi sont copiés dans le dossier court, sous leur nom d'origine.
    (work / "in").mkdir()
    local_models = []
    for m in model_paths:
        local = work / "in" / m.name
        shutil.copy2(m, local)
        if convert_to:
            edited = threemf.edit(str(local), project_overrides, output_path=str(local.with_suffix(".edit")),
                                  machine=convert_to)
            Path(edited["output"]).replace(local)
            if edited["changes"]:
                applied[m.name] = edited["changes"]
        local_models.append(f"in/{m.name}")
    args += ["--export-3mf", "result.3mf", "--outputdir", "out"] + local_models

    key = _cache_key(exe, args, [project_overrides, convert_to], model_paths, work)
    overrides = {**(filament_overrides or {}), **(process_overrides or {})}
    cached = _cache_get(key)
    if cached:
        shutil.rmtree(work, ignore_errors=True)
        history.record(model_paths, cached, machine or convert_to, process, filaments, overrides, label)
        return cached

    started = time.time()
    try:
        proc = _run_cli(args, work, timeout_s)
    except subprocess.TimeoutExpired:
        # Bambu Studio se fige parfois sans raison (0 % CPU) : un second essai passe en général.
        shutil.rmtree(work / "out", ignore_errors=True)
        try:
            proc = _run_cli(args, work, timeout_s)
        except subprocess.TimeoutExpired:
            shutil.rmtree(work, ignore_errors=True)
            raise TimeoutError(f"Bambu Studio n'a pas répondu en {timeout_s} s, deux fois de suite. "
                               "Fermer les bambu-studio.exe restés ouverts (Gestionnaire des tâches) "
                               "et réessayer.") from None
    elapsed = round(time.time() - started, 1)

    out_dir = work / "out"
    result_json = {}
    if (out_dir / "result.json").exists():
        result_json = json.loads((out_dir / "result.json").read_text(encoding="utf-8-sig"))
    # output/<projet>/<variante>/<horodatage>[_plateau-N]/ : un dossier par projet, puis par variante.
    dest = _unique_dir(model_paths[0].stem, label or "slice",
                       time.strftime("%Y%m%d-%H%M%S") + (f"_plateau-{plate}" if plate else ""))
    produced = []
    if out_dir.is_dir():
        # Le result.3mf contient déjà le G-code de chaque plateau : pas de plate_N.gcode en double à côté.
        bundled = (out_dir / "result.3mf").exists()
        for f in out_dir.iterdir():
            if f.is_file() and not (bundled and f.suffix == ".gcode"):
                shutil.move(str(f), dest / f.name)
                produced.append(str(dest / f.name))
    shutil.rmtree(work, ignore_errors=True)

    summary = {"return_code": result_json.get("return_code", proc.returncode),
               "message": result_json.get("error_string"), "cli_seconds": elapsed,
               "output_dir": str(dest), "files": produced, "overrides_applied": applied}
    plates = []
    for p in result_json.get("sliced_plates", []):
        seconds = int(p.get("total_predication") or 0)
        plates.append({
            "plate": p.get("id"), "time_s": seconds, "time": history.duration(seconds),
            "filament_g": round(sum(f.get("total_used_g", 0) for f in p.get("filaments", [])), 2),
            "filaments": p.get("filaments"), "warning": p.get("warning_message") or None,
            "time_by_feature_s": {k: round(v) for k, v in (p.get("feature_type_times") or {}).items()},
        })
    summary["plates"] = plates
    exported = dest / "result.3mf"
    if exported.exists():
        with zipfile.ZipFile(exported) as z:
            if threemf.SLICE_INFO in z.namelist():
                summary["slice_info"] = threemf.parse_slice_info(z.read(threemf.SLICE_INFO))
        summary["project_3mf"] = str(exported)
        summary["checks"] = analysis.warnings(threemf.get_settings(str(exported)))
    if summary["return_code"] != 0:
        summary["stderr"] = (proc.stderr or proc.stdout or "")[-3000:]
    else:
        _cache_put(key, summary)
    history.record(model_paths, summary, machine or convert_to, process, filaments, overrides, label)
    return summary


def _run_cli(args: list, work: Path, timeout_s: int) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(args, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # Tuer tout l'arbre : la CLI peut avoir lancé des processus enfants.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def _safe(part: str) -> str:
    """Nom utilisable comme dossier Windows."""
    return "".join("_" if c in '<>:"/\\|?*' else c for c in part).strip(" .") or "_"


def _unique_dir(project: str, variant: str, name: str) -> Path:
    """Dossier de sortie neuf, même pour des slices lancés dans la même seconde."""
    base = config.output_dir() / _safe(project) / _safe(variant)
    for i in range(1000):
        dest = base / (name if i == 0 else f"{name}-{i}")
        try:
            dest.mkdir(parents=True)
            return dest
        except FileExistsError:
            continue
    raise OSError(f"Impossible de créer un dossier de sortie pour {name}")


def _cache_key(exe: Path, args: list, project_edits: list, model_paths: list[Path], work: Path) -> str:
    """Empreinte de tout ce qui change le résultat : modèles, presets aplatis, overrides, options, version."""
    h = hashlib.sha256()
    h.update(f"{exe}|{exe.stat().st_mtime_ns}".encode())
    h.update(json.dumps([args[1:], project_edits], sort_keys=True).encode())
    for path in model_paths + sorted(work.glob("*.json")):
        h.update(path.read_bytes())
    return h.hexdigest()[:32]


def _cache_get(key: str) -> dict | None:
    entry = config.output_dir() / ".cache" / f"{key}.json"
    if not entry.exists():
        return None
    summary = json.loads(entry.read_text(encoding="utf-8"))
    # Résultat inutilisable si l'utilisateur a supprimé le dossier de sortie.
    if not all(Path(f).exists() for f in summary.get("files", [])):
        entry.unlink(missing_ok=True)
        return None
    return {**summary, "cached": True, "cli_seconds": 0}


def _cache_put(key: str, summary: dict) -> None:
    folder = config.output_dir() / ".cache"
    folder.mkdir(exist_ok=True)
    (folder / f"{key}.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


# Recettes pour une P1S buse 0.4, appliquées par-dessus les réglages du projet ou du preset.
# Le débit max du filament plafonne déjà les vitesses (15-21 mm³/s en PLA) : on joue surtout sur les
# accélérations, en restant loin des 20 000 mm/s² de la P1S. Base 0.20mm Standard : 10 000 par défaut,
# 5 000 sur le mur extérieur, 2 000 sur le dessus.
GOALS = {
    # Mur extérieur et dessus plus doux pour la finition.
    "qualite": {"layer_height": "0.16", "initial_layer_print_height": "0.2", "outer_wall_speed": "150",
                "outer_wall_acceleration": "3000", "outer_wall_line_width": "0.42", "inner_wall_speed": "250",
                "top_surface_speed": "150", "top_surface_acceleration": "1500", "top_surface_line_width": "0.42",
                "default_acceleration": "8000", "seam_position": "aligned", "enable_overhang_speed": "1",
                "slow_down_layer_time": "6"},
    "equilibre": {"layer_height": "0.2", "initial_layer_print_height": "0.2", "outer_wall_speed": "200",
                  "outer_wall_acceleration": "5000", "outer_wall_line_width": "0.42",
                  "top_surface_line_width": "0.42", "top_surface_acceleration": "2000",
                  "default_acceleration": "10000", "seam_position": "aligned", "enable_overhang_speed": "1",
                  "slow_down_layer_time": "4"},
    # Pas de lightning : il laisse les couches du dessus en pont. L'adaptive cubic reste léger au cœur
    # et se densifie sous les surfaces, avec 4 couches de dessus pour bien fermer.
    "vitesse": {"layer_height": "0.28", "wall_loops": "2", "top_shell_layers": "4", "bottom_shell_layers": "3",
                "sparse_infill_density": "12%", "sparse_infill_pattern": "adaptivecubic",
                "default_acceleration": "14000", "outer_wall_acceleration": "7000",
                "top_surface_acceleration": "3000", "slow_down_layer_time": "4"},
    "solidite": {"layer_height": "0.2", "wall_loops": "4", "top_shell_layers": "5", "bottom_shell_layers": "4",
                 "sparse_infill_density": "25%", "sparse_infill_pattern": "gyroid", "slow_down_layer_time": "4"},
    "leger": {"layer_height": "0.24", "wall_loops": "2", "top_shell_layers": "4", "bottom_shell_layers": "3",
              "sparse_infill_density": "10%", "sparse_infill_pattern": "adaptivecubic",
              "default_acceleration": "12000", "outer_wall_acceleration": "6000",
              "top_surface_acceleration": "2500", "slow_down_layer_time": "4"},
}


def _split(settings: dict, machine: str | None, process: str | None,
           filaments: list[str] | None) -> tuple[dict, dict]:
    """Avec des presets, répartit les réglages entre process et filament (sans presets : tout au projet,
    sauf la part filament quand un filament est chargé par-dessus le projet).
    Une clé inconnue des deux reste côté process, pour que l'erreur propose les bons noms."""
    if not (machine and process) and not filaments:
        return settings, {}
    filament_keys = (presets.resolve("filament", filaments[0]).keys() | presets.known_keys("filament")
                     if filaments else set())
    process_keys = (presets.resolve("process", process).keys() if process else set()) | presets.known_keys("process")
    unknown = [k for k in settings if k not in process_keys and k not in filament_keys]
    if unknown and not filaments and process:
        raise ValueError(f"Réglages absents du process {unknown} : réglages filament (indiquer `filaments`) "
                         "ou nom mal orthographié.")
    fil = {k: v for k, v in settings.items() if k in filament_keys and k not in process_keys}
    return {k: v for k, v in settings.items() if k not in fil}, fil


def _row(name: str, settings: dict, result: dict) -> dict:
    plates = result.get("plates") or []
    seconds = sum(p["time_s"] for p in plates)
    return {"name": name, "time": history.duration(seconds), "time_s": seconds,
            "weight_g": round(sum(p["filament_g"] for p in plates), 2),
            "slicer_warnings": [p["warning"] for p in plates if p.get("warning")],
            "checks": result.get("checks", []), "settings": settings,
            "plates": [{"plate": p["plate"], "time": p["time"], "time_s": p["time_s"], "weight_g": p["filament_g"]}
                       for p in plates],
            "project_3mf": result.get("project_3mf"), "cached": result.get("cached", False),
            **({"error": result.get("message") or "échec du slicing"} if result.get("return_code") else {})}


def compare(models: list[str], variants: dict[str, dict], include_original: bool = True,
            machine: str | None = None, process: str | None = None, filaments: list[str] | None = None,
            plate: int = 0, bed_type: str | None = None, max_workers: int | None = None) -> dict:
    """Slice plusieurs variantes en parallèle et renvoie un tableau comparatif."""
    jobs = ([("original", {})] if include_original else []) + list(variants.items())
    if not jobs:
        raise ValueError("Aucune variante à slicer.")
    # Un Bambu Studio par demi-cœur : mesuré 17 % plus rapide qu'un par tiers sur 12 cœurs / 16 Go.
    workers = max_workers or min(len(jobs), max(1, (os.cpu_count() or 4) // 2))
    machine, process, filaments = _default_presets(models, machine, process, filaments)

    def one(job):
        name, settings = job
        try:
            proc, fil = _split(settings, machine, process, filaments)
            result = run(models, machine, process, filaments, proc or None, fil or None, plate, bed_type,
                         label=name)
        except (KeyError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            return {"name": name, "settings": settings, "error": str(msg)}
        return _row(name, settings, result)

    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, jobs))
    ref = next((r for r in rows if r["name"] == "original" and "error" not in r), None)
    if ref and ref["time_s"]:
        for r in rows:
            if "error" not in r and r is not ref:
                r["vs_original"] = {"time_pct": round(100 * (r["time_s"] - ref["time_s"]) / ref["time_s"]),
                                    "weight_pct": round(100 * (r["weight_g"] - ref["weight_g"]) / ref["weight_g"])
                                    if ref["weight_g"] else None}
    return {"wall_seconds": round(time.time() - started, 1), "workers": workers, "variants": rows}


def optimize(models: list[str], goal: str, machine: str | None = None, process: str | None = None,
             filaments: list[str] | None = None, plate: int = 0, bed_type: str | None = None,
             compare_all: bool = True) -> dict:
    """Applique la recette de `goal` (et, si compare_all, les autres) puis désigne la variante conseillée."""
    if goal not in GOALS:
        raise ValueError(f"Objectif inconnu {goal!r} : {list(GOALS)}")
    target = machine or config.default_machine()
    chosen = {name: fit_machine(recipe, target) for name, recipe in GOALS.items() if compare_all or name == goal}
    result = compare(models, chosen, True, machine, process, filaments, plate, bed_type)
    best = next(r for r in result["variants"] if r["name"] == goal)
    # Vitesse et légèreté se mesurent : la recette ne bat pas toujours un projet déjà poussé.
    metric = {"vitesse": "time_s", "leger": "weight_g"}.get(goal)
    ok = [r for r in result["variants"] if "error" not in r]
    if metric and ok:
        best = min(ok, key=lambda r: r[metric])
    result["goal"] = goal
    result["recommended"] = best["name"]
    if "error" not in best:
        result["how_to_apply"] = ("edit_3mf avec ces réglages (settings) pour un projet, "
                                  "ou save_preset pour en faire un preset.")
    return result
