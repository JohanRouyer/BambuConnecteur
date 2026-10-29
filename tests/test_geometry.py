import numpy as np
import pytest

from bambu_mcp import geometry
from conftest import box, funnel, write_3mf, write_stl


@pytest.mark.parametrize("ascii", [False, True])
def test_stl_cube(tmp_path, ascii):
    a = geometry.analyze(str(write_stl(box(10, 20, 30), tmp_path / "c.stl", ascii)))
    assert a["triangles"] == 12
    assert a["volume_cm3"] == pytest.approx(6.0)
    assert a["current"]["size_mm"] == [10, 20, 30]
    assert a["current"]["base_area_mm2"] == pytest.approx(200)
    assert a["current"]["overhang_pct"] == 0 and not a["current"]["needs_support"]
    assert a["current"]["fits_bed"]


def test_too_big_for_p1s(tmp_path):
    a = geometry.analyze(str(write_stl(box(300, 300, 300), tmp_path / "big.stl")))
    assert not any(r["fits_bed"] for r in a["orientations"])
    assert any("Too big" in x for x in a["advice"])


def test_tall_part_fits_lying_down(tmp_path):
    # 252 mm: too tall standing (max 250) but fits lying down (256 bed).
    a = geometry.analyze(str(write_stl(box(20, 20, 252), tmp_path / "tall.stl")))
    assert not a["current"]["fits_bed"]
    best = next(r for r in a["orientations"] if r["orientation"] == a["best_orientation"])
    assert best["fits_bed"] and best["size_mm"][2] == 20


def test_overhang_and_best_orientation(tmp_path):
    a = geometry.analyze(str(write_stl(funnel(), tmp_path / "f.stl")))
    assert a["current"]["needs_support"]
    assert a["best_orientation"] == "upside down"
    flipped = next(r for r in a["orientations"] if r["orientation"] == "upside down")
    assert not flipped["needs_support"]
    assert flipped["base_area_mm2"] == pytest.approx(2500)


def test_horizontal_faces_are_bridges(tmp_path):
    # Table: a 40 x 40 top on a 10 x 10 central leg (two boxes that are not merged:
    # the whole underside of the top counts).
    tris = np.concatenate([box(10, 10, 20) + [15, 15, 0], box(40, 40, 5) + [0, 0, 20]])
    a = geometry.analyze(str(write_stl(tris, tmp_path / "t.stl")))
    assert a["current"]["bridge_area_mm2"] == pytest.approx(1600, abs=1)
    assert a["current"]["overhang_pct"] == 0


def test_rotated_stl_sits_on_bed(tmp_path):
    out = geometry.write_rotated_stl(str(write_stl(funnel(), tmp_path / "f.stl")), 180, 0, tmp_path / "r.stl")
    tris = geometry.load(str(out))
    assert tris[:, :, 2].min() == pytest.approx(0, abs=1e-4)
    assert geometry.analyze(str(out))["best_orientation"] == "as is"


@pytest.mark.parametrize("split", [False, True])
def test_3mf_with_build_transform(tmp_path, split):
    # 90° rotation around Z then translation, in 3MF format (row vectors).
    path = write_3mf(box(10, 20, 30), tmp_path / "m.3mf", "0 1 0 -1 0 0 0 0 1 100 50 0", split)
    tris = geometry.load(str(path))
    mins, maxs = tris.reshape(-1, 3).min(axis=0), tris.reshape(-1, 3).max(axis=0)
    assert list(np.round(maxs - mins)) == [20, 10, 30]
    assert list(np.round(mins)) == [80, 50, 0]


def test_unknown_format(tmp_path):
    p = tmp_path / "m.obj"
    p.write_text("")
    with pytest.raises(ValueError):
        geometry.load(str(p))
