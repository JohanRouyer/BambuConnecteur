"""Checks on a set of Bambu settings: volumetric flow, machine speeds, common pitfalls."""
from . import threemf

# Line type -> (speed key, line width key, layer height key).
FEATURES = {
    "outer_wall": ("outer_wall_speed", "outer_wall_line_width", "layer_height"),
    "inner_wall": ("inner_wall_speed", "inner_wall_line_width", "layer_height"),
    "sparse_infill": ("sparse_infill_speed", "sparse_infill_line_width", "layer_height"),
    "internal_solid_infill": ("internal_solid_infill_speed", "internal_solid_infill_line_width", "layer_height"),
    "top_surface": ("top_surface_speed", "top_surface_line_width", "layer_height"),
    "gap_infill": ("gap_infill_speed", "line_width", "layer_height"),
    "support": ("support_speed", "support_line_width", "layer_height"),
    "initial_layer": ("initial_layer_speed", "initial_layer_line_width", "initial_layer_print_height"),
    "initial_layer_infill": ("initial_layer_infill_speed", "initial_layer_line_width", "initial_layer_print_height"),
}


def _num(value, default: float = 0.0) -> float:
    """First number of a Bambu value (string or list of variants)."""
    if isinstance(value, list):
        value = value[0] if value else ""
    try:
        return float(str(value).rstrip("%"))
    except ValueError:
        return default


def _line_width(ps: dict, key: str) -> float:
    nozzle = _num(ps.get("nozzle_diameter"), 0.4)
    raw = ps.get(key)
    raw = raw[0] if isinstance(raw, list) and raw else raw
    if isinstance(raw, str) and raw.endswith("%"):
        return nozzle * _num(raw) / 100
    width = _num(raw)
    if not width and key != "line_width":
        return _line_width(ps, "line_width")
    # 0 = Bambu Studio's automatic width.
    return width or nozzle * 1.125


def flow_check(ps: dict) -> list[dict]:
    """Requested flow per line type, compared with the filament's max volumetric speed.
    Bambu Studio caps speed at that flow: above it, the set speed is never reached."""
    max_flow = _num(ps.get("filament_max_volumetric_speed"))
    rows = []
    for feature, (speed_key, width_key, height_key) in FEATURES.items():
        speed = _num(ps.get(speed_key))
        if feature == "support" and ps.get("enable_support") != "1":
            continue
        if not speed:
            continue
        width, height = _line_width(ps, width_key), _num(ps.get(height_key))
        flow = speed * width * height
        row = {"feature": feature, "speed": speed, "flow_mm3_s": round(flow, 1)}
        if max_flow and flow > max_flow:
            row["capped_speed"] = round(max_flow / (width * height))
        rows.append(row)
    return rows


def warnings(ps: dict) -> list[str]:
    """Common pitfalls, in plain words."""
    out = []
    max_flow = _num(ps.get("filament_max_volumetric_speed"))
    capped = [r for r in flow_check(ps) if "capped_speed" in r]
    if capped:
        details = ", ".join(f"{r['feature']} {r['speed']:g}→{r['capped_speed']} mm/s" for r in capped)
        out.append(f"Filament max flow ({max_flow:g} mm³/s) reached: actual speeds are capped ({details}).")
    machine_max = _num(ps.get("machine_max_speed_x"))
    too_fast = [k for k, _, _ in FEATURES.values() if machine_max and _num(ps.get(k)) > machine_max]
    if too_fast:
        out.append(f"Speeds above the machine maximum ({machine_max:g} mm/s): {too_fast}.")
    if _num(ps.get("slow_down_for_layer_cooling"), 1) and _num(ps.get("slow_down_layer_time"), 1) == 0:
        out.append("slow_down_layer_time = 0: no slowdown on small layers "
                   "(chimneys, tips and fine details may melt).")
    if not _num(ps.get("slow_down_for_layer_cooling"), 1):
        out.append("Slowdown for layer cooling disabled (slow_down_for_layer_cooling = 0).")
    nozzle = _num(ps.get("nozzle_diameter"), 0.4)
    layer = _num(ps.get("layer_height"))
    if layer > nozzle * 0.75:
        out.append(f"{layer:g} mm layers are too thick for a {nozzle:g} mm nozzle (recommended max {nozzle * 0.75:g}).")
    if _num(ps.get("wall_loops"), 2) < 2:
        out.append("A single wall: fragile part and uneven surfaces.")
    if ps.get("sparse_infill_pattern") == "lightning":
        out.append("Lightning infill: top layers bridge over large gaps (sagging or holed top surfaces); "
                   "adaptivecubic keeps the weight saving without this flaw.")
    ftype = ps.get("filament_type")
    ftype = (ftype[0] if isinstance(ftype, list) and ftype else ftype) or ""
    if ftype.upper() in ("ABS", "ASA", "PC", "PA") and _num(ps.get("fan_max_speed"), 0) > 60:
        out.append(f"{ftype} with the fan up to {_num(ps.get('fan_max_speed')):g} %: risk of delamination "
                   "(close the enclosure, reduce cooling).")
    if ftype.upper() == "TPU":
        out.append("TPU: feed it from the external spool, not the AMS.")
    return out


def check_3mf(path: str) -> dict:
    ps = threemf.get_settings(path)
    return {"filament_max_volumetric_speed": _num(ps.get("filament_max_volumetric_speed")),
            "flow": flow_check(ps), "warnings": warnings(ps)}
