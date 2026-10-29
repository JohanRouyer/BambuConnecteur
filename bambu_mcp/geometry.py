"""Model geometry (STL, 3MF): size, volume, overhangs, best orientation on the printer."""
import re
import struct
import zipfile
from pathlib import Path

import numpy as np

from . import config, presets

# Fallback build volume (P1S) when the printer preset cannot be read.
BED = (256.0, 256.0, 250.0)
# A downward face more than 60° from vertical usually needs support; between 45 and 60° a Bambu
# copes with good cooling. Horizontal faces are bridges.
OVERHANG_ANGLE = 60
BRIDGE_NZ = -0.985

# Tested orientations, named after the applied rotation (degrees around X then Y).
ORIENTATIONS = {
    "as is": (0, 0), "upside down": (180, 0), "tipped forward": (90, 0),
    "tipped backward": (-90, 0), "on its left side": (0, 90), "on its right side": (0, -90),
}


def bed() -> tuple[float, float, float]:
    """Build volume (X, Y, Z in mm) of the default printer, read from its preset."""
    try:
        cfg = presets.resolve("machine", config.default_machine())
        xs, ys = zip(*(map(float, corner.split("x")) for corner in cfg["printable_area"]))
        return max(xs) - min(xs), max(ys) - min(ys), float(cfg["printable_height"])
    except (KeyError, ValueError, OSError):
        return BED


def _rotation(rx: float, ry: float) -> np.ndarray:
    ax, ay = np.radians(rx), np.radians(ry)
    rot_x = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    rot_y = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    return rot_y @ rot_x


def _read_stl(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + count * 50 == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=count, offset=84)
            return rec["v"].astype(np.float64)
    nums = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    if not nums:
        raise ValueError(f"Unreadable STL: {path}")
    return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)


_VERTEX = re.compile(rb'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"')
_TRIANGLE = re.compile(rb'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"')
_MATRIX = re.compile(r'transform="([^"]+)"')


def _transform(attr: str | None) -> np.ndarray:
    """3MF matrix (12 numbers, row vectors) to a 4x4 homogeneous matrix."""
    m = np.eye(4)
    if attr:
        vals = np.array(attr.split(), dtype=np.float64)
        m[:3, :3] = vals[:9].reshape(3, 3).T
        m[:3, 3] = vals[9:12]
    return m


def _mesh_objects(xml: bytes) -> dict:
    """Meshes of a .model file: {object id: triangles (n, 3, 3)}."""
    out = {}
    for match in re.finditer(rb'<object id="(\d+)"[^>]*>(.*?)</object>', xml, re.S):
        body = match.group(2)
        if b"<mesh" not in body:
            continue
        verts = np.array(_VERTEX.findall(body), dtype=np.float64)
        tris = np.array(_TRIANGLE.findall(body), dtype=np.int64)
        if len(verts) and len(tris):
            out[match.group(1).decode()] = verts[tris]
    return out


def _read_3mf(path: Path) -> np.ndarray:
    """Every object on the plate, with build transforms applied."""
    with zipfile.ZipFile(path) as z:
        main = z.read("3D/3dmodel.model")
        files = {"/3D/3dmodel.model": main}
        for name in z.namelist():
            if name.startswith("3D/") and name.endswith(".model") and name != "3D/3dmodel.model":
                files["/" + name] = z.read(name)
    meshes = {(p, oid): tris for p, xml in files.items() for oid, tris in _mesh_objects(xml).items()}
    text = main.decode("utf-8", "replace")
    components = {}
    for match in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', text, re.S):
        comps = re.findall(r"<component ([^>]*)/>", match.group(2))
        components[match.group(1)] = [
            (re.search(r'p:path="([^"]+)"', c).group(1) if 'p:path="' in c else "/3D/3dmodel.model",
             re.search(r'objectid="(\d+)"', c).group(1),
             _transform(_MATRIX.search(c).group(1) if _MATRIX.search(c) else None)) for c in comps]
    parts = []
    for item in re.findall(r"<item ([^>]*)/>", text):
        oid = re.search(r'objectid="(\d+)"', item).group(1)
        build = _transform(_MATRIX.search(item).group(1) if _MATRIX.search(item) else None)
        refs = components.get(oid) or [("/3D/3dmodel.model", oid, np.eye(4))]
        for p, sub, local in refs:
            tris = meshes.get((p, sub))
            if tris is None:
                continue
            m = build @ local
            parts.append(tris @ m[:3, :3].T + m[:3, 3])
    if not parts:
        raise ValueError(f"No mesh found in {path}")
    return np.concatenate(parts)


def load(path: str) -> np.ndarray:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Model not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".stl":
        return _read_stl(p)
    if suffix == ".3mf":
        return _read_3mf(p)
    raise ValueError(f"Unsupported format: {suffix} (STL or 3MF).")


def _metrics(tris: np.ndarray) -> dict:
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    with np.errstate(invalid="ignore", divide="ignore"):
        nz = np.nan_to_num(cross[:, 2] / (2 * area))
    zmin = tris[:, :, 2].min()
    zc = tris[:, :, 2].mean(axis=1)
    on_bed = (nz < -0.99) & (tris[:, :, 2].max(axis=1) < zmin + 0.05)
    floating = ~on_bed & (zc > zmin + 0.3)
    bridge = floating & (nz < BRIDGE_NZ)
    overhang = floating & (nz < -np.sin(np.radians(OVERHANG_ANGLE))) & ~bridge
    size = tris.reshape(-1, 3).max(axis=0) - tris.reshape(-1, 3).min(axis=0)
    return {"size_mm": [round(float(s), 1) for s in size], "base_area_mm2": round(float(area[on_bed].sum()), 1),
            "overhang_area_mm2": round(float(area[overhang].sum()), 1),
            "bridge_area_mm2": round(float(area[bridge].sum()), 1), "surface_mm2": float(area.sum())}


def analyze(path: str) -> dict:
    """Dimensions, volume, fit on the bed and overhangs for each simple orientation."""
    tris = load(path)
    tris = tris - tris.reshape(-1, 3).mean(axis=0)
    volume = abs(float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum()) / 6)
    volume_mm = bed()
    rows = []
    for name, (rx, ry) in ORIENTATIONS.items():
        m = _metrics(tris @ _rotation(rx, ry).T)
        fits = (all(s <= b for s, b in zip(sorted(m["size_mm"][:2]), sorted(volume_mm[:2])))
                and m["size_mm"][2] <= volume_mm[2])
        rows.append({"orientation": name, "rotate_x": rx, "rotate_y": ry, **m, "fits_bed": fits})
    surface = rows[0]["surface_mm2"]
    for r in rows:
        r.pop("surface_mm2")
        r["overhang_pct"] = round(100 * r["overhang_area_mm2"] / surface, 1) if surface else 0
        r["bridge_pct"] = round(100 * r["bridge_area_mm2"] / surface, 1) if surface else 0
        r["needs_support"] = r["overhang_pct"] > 2
    # Fewest overhangs (bridges count half), then best footprint, then lowest height.
    best = min((r for r in rows if r["fits_bed"]), default=rows[0],
               key=lambda r: (round(r["overhang_pct"] + r["bridge_pct"] / 2), -r["base_area_mm2"], r["size_mm"][2]))
    current = rows[0]
    advice = []
    if not current["fits_bed"]:
        advice.append(f"Too big for the printer as is ({' x '.join(f'{b:g}' for b in volume_mm)} mm): "
                      "reorient, scale down or split.")
    if current["needs_support"]:
        advice.append(f"{current['overhang_pct']} % of the surface overhangs more than {OVERHANG_ANGLE}°: "
                      "supports probably needed (check the slicer warnings).")
    if current["bridge_pct"] > 5:
        advice.append(f"{current['bridge_pct']} % bridges (horizontal faces over air): "
                      "fine over short spans, otherwise supports.")
    if current["base_area_mm2"] < 50:
        advice.append("Small contact area with the bed: add a brim.")
    w, d, h = current["size_mm"]
    if min(w, d) and h / min(w, d) > 4:
        advice.append("Tall and thin part: brim recommended, slower speed near the top.")
    if best is not current:
        advice.append(f"Estimated best orientation: {best['orientation']!r}.")
    return {"file": path, "machine": config.default_machine(), "bed_mm": list(volume_mm),
            "triangles": int(len(tris)), "volume_cm3": round(volume / 1000, 2),
            "solid_weight_pla_g": round(volume / 1000 * 1.24, 1), "current": current,
            "best_orientation": best["orientation"], "orientations": rows, "advice": advice,
            "note": "Geometric estimate: bridges and small overhangs often print fine without support."}


def write_rotated_stl(path: str, rx: float, ry: float, dest: Path) -> Path:
    """Rotated binary STL copy, resting on Z = 0."""
    tris = load(path) @ _rotation(rx, ry).T
    tris[:, :, 2] -= tris[:, :, 2].min()
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    norms = np.linalg.norm(cross, axis=1, keepdims=True)
    normals = np.divide(cross, norms, out=np.zeros_like(cross), where=norms > 0)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = normals, tris
    dest.write_bytes(b"\0" * 80 + struct.pack("<I", len(tris)) + rec.tobytes())
    return dest
