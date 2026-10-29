"""Logique pure : contrôles, normalisation des réglages, cache, historique, matériaux."""
import json

import pytest

from bambu_mcp import analysis, history, materials, presets, slicer

PS = {"layer_height": "0.2", "initial_layer_print_height": "0.2", "nozzle_diameter": ["0.4"],
      "line_width": "0.42", "outer_wall_line_width": "0.42", "inner_wall_line_width": "0.45",
      "outer_wall_speed": ["200"], "inner_wall_speed": ["300"], "filament_max_volumetric_speed": ["21"],
      "machine_max_speed_x": ["500"], "slow_down_for_layer_cooling": ["1"], "slow_down_layer_time": ["4"],
      "wall_loops": "2", "filament_type": ["PLA"], "fan_max_speed": ["100"], "enable_support": "0"}


def test_flow_and_capped_speed():
    rows = {r["feature"]: r for r in analysis.flow_check(PS)}
    assert rows["outer_wall"]["flow_mm3_s"] == pytest.approx(16.8)
    assert "capped_speed" not in rows["outer_wall"]
    assert rows["inner_wall"]["flow_mm3_s"] == pytest.approx(27.0)
    assert rows["inner_wall"]["capped_speed"] == round(21 / (0.45 * 0.2))
    assert "support" not in rows  # supports désactivés


def test_line_width_percent_and_auto():
    ps = dict(PS, outer_wall_line_width="110%", inner_wall_line_width="0")
    rows = {r["feature"]: r for r in analysis.flow_check(ps)}
    assert rows["outer_wall"]["flow_mm3_s"] == pytest.approx(200 * 0.44 * 0.2, abs=0.1)
    assert rows["inner_wall"]["flow_mm3_s"] == pytest.approx(300 * 0.42 * 0.2, abs=0.1)  # retombe sur line_width


def test_clean_settings_have_only_flow_warning():
    w = analysis.warnings(PS)
    assert len(w) == 1 and "Débit max" in w[0]


@pytest.mark.parametrize("change, expected", [
    ({"slow_down_layer_time": ["0"]}, "slow_down_layer_time = 0"),
    ({"slow_down_for_layer_cooling": ["0"]}, "désactivé"),
    ({"layer_height": "0.32"}, "trop épaisse"),
    ({"wall_loops": "1"}, "Une seule paroi"),
    ({"outer_wall_speed": ["600"]}, "maximum machine"),
    ({"filament_type": ["ABS"]}, "délaminage"),
    ({"filament_type": ["TPU"]}, "bobine externe"),
])
def test_warnings(change, expected):
    assert any(expected in w for w in analysis.warnings(dict(PS, **change)))


def test_normalize():
    assert presets.normalize("0.2", 0.16) == "0.16"
    assert presets.normalize(["4", "4"], 6) == ["6", "6"]
    assert presets.normalize("0", True) == "1"
    with pytest.raises(ValueError):
        presets.normalize("0.2", [1, 2])


def test_apply_settings_unknown_and_known():
    with pytest.raises(KeyError) as exc:
        presets.apply_settings({"layer_height": "0.2"}, {"layer_heigth": "0.3"})
    assert "layer_height" in str(exc.value)
    norm, changes = presets.apply_settings({"layer_height": "0.2"}, {"brim_type": "no_brim"},
                                           known=frozenset({"brim_type"}))
    assert norm == {"brim_type": "no_brim"} and changes[0]["before"] is None


def test_unique_dirs_do_not_collide(isolated_output):
    dirs = {slicer._unique_dir("x", "vitesse", "20260101-000000") for _ in range(3)}
    assert len(dirs) == 3
    assert all(d.parent == isolated_output / "x" / "vitesse" for d in dirs)


def test_unique_dir_sanitizes_names(isolated_output):
    d = slicer._unique_dir("a:b", "v/1", "t")
    assert d == isolated_output / "a_b" / "v_1" / "t"


def test_cache_roundtrip_and_invalidation(isolated_output):
    produced = isolated_output / "r.3mf"
    produced.write_text("x")
    slicer._cache_put("k", {"files": [str(produced)], "cli_seconds": 4.2})
    hit = slicer._cache_get("k")
    assert hit["cached"] and hit["cli_seconds"] == 0
    produced.unlink()
    assert slicer._cache_get("k") is None
    assert not (isolated_output / ".cache" / "k.json").exists()


def test_history_order_and_search():
    summary = {"return_code": 0, "plates": [{"time_s": 3700, "filament_g": 9.5}], "checks": ["a"]}
    history.record(["C:/a/benchy.3mf"], summary, None, None, None, {}, "equilibre")
    history.record(["C:/a/support.stl"], summary, None, None, None, {"layer_height": "0.2"}, None)
    rows = history.read()
    assert [r["models"][0][-11:] for r in rows] == ["support.stl", "/benchy.3mf"]
    assert rows[0]["time"] == "1h01" and rows[0]["checks"] == 1
    assert len(history.read(search="benchy equilibre")) == 1
    assert len(history.read(limit=1)) == 1


def test_history_skips_corrupt_lines(isolated_output):
    (isolated_output / "history.jsonl").write_text('pas du json\n' + json.dumps({"models": ["m"]}) + "\n")
    assert len(history.read()) == 1


def test_materials_aliases():
    assert materials.find("petg hf")[0] == "PETG"
    assert materials.find("pla")[0] == "PLA"
    with pytest.raises(KeyError):
        materials.find("bois")


def test_split_without_presets_keeps_everything():
    assert slicer._split({"a": "1"}, None, None, None) == ({"a": "1"}, {})
