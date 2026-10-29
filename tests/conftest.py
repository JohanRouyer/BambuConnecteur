"""Shared helpers: test meshes generated on the fly, isolated config and output folder."""
import json
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bambu_mcp import config  # noqa: E402

HAS_BAMBU = config.executable().exists()
needs_bambu = pytest.mark.skipif(not HAS_BAMBU, reason="Bambu Studio not installed")


def solid(vertices, quads) -> np.ndarray:
    """Triangles (n, 3, 3) of a convex solid, facing outward."""
    v = np.array(vertices, dtype=float)
    center = v.mean(axis=0)
    tris = []
    for q in quads:
        for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            tri = v[list(t)]
            if np.dot(np.cross(tri[1] - tri[0], tri[2] - tri[0]), tri.mean(axis=0) - center) < 0:
                tri = tri[[0, 2, 1]]
            tris.append(tri)
    return np.array(tris)


QUADS = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def box(sx, sy, sz) -> np.ndarray:
    return solid([(0, 0, 0), (sx, 0, 0), (sx, sy, 0), (0, sy, 0),
                  (0, 0, sz), (sx, 0, sz), (sx, sy, sz), (0, sy, sz)], QUADS)


def funnel() -> np.ndarray:
    """Truncated pyramid standing on its small face: sides 63° from vertical, so overhanging."""
    return solid([(20, 20, 0), (30, 20, 0), (30, 30, 0), (20, 30, 0),
                  (0, 0, 10), (50, 0, 10), (50, 50, 10), (0, 50, 10)], QUADS)


def write_stl(tris: np.ndarray, path: Path, ascii: bool = False) -> Path:
    if ascii:
        lines = ["solid t"]
        for t in tris:
            lines += ["facet normal 0 0 0", "outer loop", *[f"vertex {x} {y} {z}" for x, y, z in t],
                      "endloop", "endfacet"]
        path.write_text("\n".join(lines + ["endsolid t"]))
        return path
    # Real normals: Bambu Studio mistakes a binary STL whose bytes are all < 128 for a text STL
    # (a 10 mm cube with null normals, for instance) and fails to read it.
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    body = b"".join(n.astype("<f4").tobytes() + t.astype("<f4").tobytes() + b"\0\0" for n, t in zip(normals, tris))
    path.write_bytes(b"\0" * 80 + struct.pack("<I", len(tris)) + body)
    return path


def write_3mf(tris: np.ndarray, path: Path, transform: str = "1 0 0 0 1 0 0 0 1 0 0 0",
              split: bool = False) -> Path:
    """Minimal 3MF; `split` puts the mesh in a separate file, like Bambu Studio does."""
    verts, index = [], {}
    faces = []
    for t in tris:
        ids = []
        for p in map(tuple, t):
            ids.append(index.setdefault(p, len(index)))
            if len(index) > len(verts):
                verts.append(p)
        faces.append(ids)
    mesh = ("<mesh><vertices>" + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
            + "</vertices><triangles>" + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
            + "</triangles></mesh>")
    ns = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
          'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"')
    with zipfile.ZipFile(path, "w") as z:
        if split:
            z.writestr("3D/Objects/part.model", f'<model {ns}><resources><object id="1" type="model">{mesh}'
                                                 "</object></resources></model>")
            obj = ('<object id="2" type="model"><components><component p:path="/3D/Objects/part.model" '
                   'objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>')
            oid = 2
        else:
            obj, oid = f'<object id="1" type="model">{mesh}</object>', 1
        z.writestr("3D/3dmodel.model", f'<model {ns}><resources>{obj}</resources>'
                                       f'<build><item objectid="{oid}" transform="{transform}"/></build></model>')
    return path


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Test config.json: the user's paths are kept, defaults removed (P1S)."""
    real = {k: v for k, v in config.load().items() if not k.startswith("default_")}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(real), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    """Each test writes to its own output folder (cache and history included)."""
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(config, "output_dir", lambda: out)
    return out
