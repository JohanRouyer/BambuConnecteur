"""Bout en bout avec le vrai Bambu Studio (ignorés s'il n'est pas installé). Environ 1 min."""
import asyncio

import pytest

from bambu_mcp import analysis, config, history, materials, prepare, server, slicer, threemf
from conftest import box, funnel, needs_bambu, write_stl

pytestmark = needs_bambu

MACHINE = "Bambu Lab P1S 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL X1C"
PLA = ["Bambu PLA Basic @BBL P1S 0.4 nozzle"]


@pytest.fixture(scope="session")
def project(tmp_path_factory):
    """Projet Bambu complet fabriqué à partir d'un cube de 20 mm."""
    root = tmp_path_factory.mktemp("projet")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "output_dir", lambda: root)
        stl = write_stl(box(20, 20, 20), root / "cube.stl")
        result = slicer.run([str(stl)], MACHINE, PROCESS, PLA, arrange=True)
    assert result["return_code"] == 0, result.get("stderr")
    return result


def test_stl_becomes_bambu_project(project):
    assert project["plates"][0]["time_s"] > 0
    assert 0 < project["plates"][0]["filament_g"] < 10
    assert threemf.get_settings(project["project_3mf"], "printer_settings_id")["printer_settings_id"] == MACHINE
    assert isinstance(project["checks"], list)


def test_project_overrides_leave_original_untouched(project):
    r = slicer.run([project["project_3mf"]], process_overrides={"layer_height": "0.28"})
    assert r["return_code"] == 0
    assert threemf.get_settings(r["project_3mf"], "layer_height")["layer_height"] == "0.28"
    assert threemf.get_settings(project["project_3mf"], "layer_height")["layer_height"] == "0.2"


def test_cache_and_history(project):
    first = slicer.run([project["project_3mf"]], process_overrides={"wall_loops": "3"})
    second = slicer.run([project["project_3mf"]], process_overrides={"wall_loops": "3"})
    assert not first.get("cached") and second["cached"]
    assert second["project_3mf"] == first["project_3mf"]
    rows = history.read()
    assert len(rows) == 2 and rows[0]["cached"] and rows[0]["overrides"] == {"wall_loops": "3"}


def test_compare_runs_in_parallel(project):
    r = slicer.compare([project["project_3mf"]], {"fin": {"layer_height": "0.12"}, "gros": {"layer_height": "0.28"},
                                                  "faute": {"layer_heigth": "0.2"}})
    rows = {v["name"]: v for v in r["variants"]}
    assert set(rows) == {"original", "fin", "gros", "faute"}
    assert "layer_height" in rows["faute"]["error"]
    assert rows["gros"]["time_s"] < rows["original"]["time_s"] < rows["fin"]["time_s"]
    assert rows["fin"]["vs_original"]["time_pct"] > 0
    assert len({rows[n]["project_3mf"] for n in ("original", "fin", "gros")}) == 3


def test_default_only_setting_through_presets(tmp_path):
    stl = write_stl(box(20, 20, 20), tmp_path / "c.stl")
    r = slicer.run([str(stl)], MACHINE, PROCESS, PLA, {"brim_type": "outer_only"}, {"slow_down_layer_time": "7"},
                   arrange=True)
    s = threemf.get_settings(r["project_3mf"], "brim_type slow_down_layer_time")
    assert s["brim_type"] == "outer_only" and s["slow_down_layer_time"] == ["7"]


@pytest.mark.parametrize("kwargs, message", [
    ({"process": PROCESS}, "machine"),
    ({"machine": MACHINE, "process_overrides": {"layer_height": "0.2"}}, "process"),
])
def test_argument_errors(tmp_path, kwargs, message):
    stl = write_stl(box(10, 10, 10), tmp_path / "c.stl")
    with pytest.raises(ValueError, match=message):
        slicer.run([str(stl)], **kwargs)


def test_overrides_on_stl_need_presets(tmp_path):
    stl = write_stl(box(10, 10, 10), tmp_path / "c.stl")
    with pytest.raises(ValueError, match="3MF"):
        slicer.run([str(stl)], process_overrides={"layer_height": "0.2"})


def test_prepare_flips_funnel_and_skips_supports(tmp_path):
    r = prepare.prepare([str(write_stl(funnel(), tmp_path / "f.stl"))], material="PETG", copies=2)
    assert r["ok"], r.get("stderr")
    assert any("retourné" in d for d in r["decisions"])
    assert r["settings"]["enable_support"] == "0"
    assert r["models"][0]["orientation"] == "retourné"
    assert r["plates"] == 1


def test_prepare_as_is_adds_supports_and_nozzle_warning(tmp_path):
    r = prepare.prepare([str(write_stl(funnel(), tmp_path / "f.stl"))], material="PLA-CF", orientation="as_is")
    assert r["ok"]
    assert r["settings"]["enable_support"] == "1"
    assert any("acier trempé" in w for w in r["warnings"])


def test_material_guide_every_material():
    for name in materials.MATERIALS:
        g = materials.guide(name)
        assert g["nozzle_c"] and g["bed_c"], name
        assert "0" not in g["bed_c"].values()
        assert all(p in g["bed_c"] for p in g["plates"]), name


def test_check_settings_on_project(project):
    c = analysis.check_3mf(project["project_3mf"])
    assert c["filament_max_volumetric_speed"] == 21 and c["flow"]


def test_server_exposes_all_tools():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"slice_model", "compare_slices", "optimize", "check_settings", "prepare_print", "analyze_model",
            "material_guide", "slice_history", "printer_status"} <= names


def test_frozen_cli_is_retried_once(tmp_path, monkeypatch):
    real, calls = slicer._run_cli, []

    def freeze_first(args, work, timeout_s):
        calls.append(1)
        if len(calls) == 1:
            raise slicer.subprocess.TimeoutExpired(args, timeout_s)
        return real(args, work, timeout_s)

    monkeypatch.setattr(slicer, "_run_cli", freeze_first)
    stl = write_stl(box(10, 10, 10), tmp_path / "c.stl")
    assert slicer.run([str(stl)], MACHINE, PROCESS, PLA, arrange=True)["return_code"] == 0
    assert len(calls) == 2


def test_frozen_twice_gives_clear_error(tmp_path, monkeypatch):
    def freeze(args, work, timeout_s):
        raise slicer.subprocess.TimeoutExpired(args, timeout_s)

    monkeypatch.setattr(slicer, "_run_cli", freeze)
    stl = write_stl(box(10, 10, 10), tmp_path / "c.stl")
    with pytest.raises(TimeoutError, match="deux fois"):
        slicer.run([str(stl)], MACHINE, PROCESS, PLA, arrange=True)
