"""Slicing et export de projets via la ligne de commande de Bambu Studio."""
import json
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from . import config, presets, threemf


def _flatten(kind: str, name: str, overrides: dict | None, dest: Path) -> list:
    """Écrit le preset entièrement résolu : la CLI ne connaît pas les presets utilisateur."""
    cfg = presets.resolve(kind, name)
    changes = []
    if overrides:
        normalized, changes = presets.apply_settings(cfg, overrides)
        cfg.update(normalized)
    cfg.update({"name": name, "type": kind, "from": "system", "inherits": "",
                "version": presets.find(kind, name)[2].get("version", "")})
    dest.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    return changes


def run(models: list[str], machine: str | None = None, process: str | None = None,
        filaments: list[str] | None = None, process_overrides: dict | None = None,
        filament_overrides: dict | None = None, plate: int = 0,
        bed_type: str | None = None, orient: bool = False, arrange: bool = False,
        timeout_s: int = 900) -> dict:
    """Lance bambu-studio.exe. Sans presets, un 3MF Bambu garde ses propres réglages."""
    exe = config.executable()
    if not exe.exists():
        raise FileNotFoundError(f"Bambu Studio introuvable : {exe}")
    model_paths = [Path(m).resolve() for m in models]
    for m in model_paths:
        if not m.exists():
            raise FileNotFoundError(f"Modèle introuvable : {m}")
    if (process or filaments) and not machine:
        raise ValueError("Indiquer aussi `machine` quand on charge des presets.")
    if machine and process_overrides and not process:
        raise ValueError("`process_overrides` avec `machine` demande aussi `process`.")
    if machine and filament_overrides and not filaments:
        raise ValueError("`filament_overrides` avec `machine` demande aussi `filaments`.")
    # Sans presets, les overrides s'appliquent aux réglages propres du projet 3MF.
    project_overrides = {} if machine else {**(filament_overrides or {}), **(process_overrides or {})}
    if project_overrides and any(m.suffix.lower() != ".3mf" for m in model_paths):
        raise ValueError("Sans `machine`, les overrides ne s'appliquent qu'à un projet 3MF Bambu.")

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
        if project_overrides:
            edited = threemf.edit(str(local), project_overrides, output_path=str(local.with_suffix(".edit")))
            Path(edited["output"]).replace(local)
            applied[m.name] = edited["changes"]
        local_models.append(f"in/{m.name}")
    args += ["--export-3mf", "result.3mf", "--outputdir", "out"] + local_models

    started = time.time()
    proc = subprocess.run(args, cwd=work, capture_output=True, text=True, timeout=timeout_s)
    elapsed = round(time.time() - started, 1)

    out_dir = work / "out"
    result_json = {}
    if (out_dir / "result.json").exists():
        result_json = json.loads((out_dir / "result.json").read_text(encoding="utf-8-sig"))
    dest = config.output_dir() / f"{model_paths[0].stem}_{time.strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    produced = []
    if out_dir.is_dir():
        for f in out_dir.iterdir():
            if f.is_file():
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
            "plate": p.get("id"), "time_s": seconds, "time": f"{seconds // 3600}h{(seconds % 3600) // 60:02d}",
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
    if summary["return_code"] != 0:
        summary["stderr"] = (proc.stderr or proc.stdout or "")[-3000:]
    return summary
