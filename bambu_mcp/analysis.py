"""Contrôles d'un jeu de réglages Bambu : débit volumétrique, vitesses machine, pièges courants."""
from . import threemf

# Type de ligne -> (clé de vitesse, clé de largeur, clé de hauteur de couche).
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
    """Premier nombre d'une valeur Bambu (chaîne ou liste de variantes)."""
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
    # 0 = largeur automatique de Bambu Studio.
    return width or nozzle * 1.125


def flow_check(ps: dict) -> list[dict]:
    """Débit demandé par type de ligne, comparé au débit max du filament.
    Bambu Studio plafonne la vitesse au débit max : au-delà, la vitesse réglée n'est pas atteinte."""
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
    """Pièges courants sur P1S, en clair."""
    out = []
    max_flow = _num(ps.get("filament_max_volumetric_speed"))
    capped = [r for r in flow_check(ps) if "capped_speed" in r]
    if capped:
        details = ", ".join(f"{r['feature']} {r['speed']:g}→{r['capped_speed']} mm/s" for r in capped)
        out.append(f"Débit max du filament ({max_flow:g} mm³/s) atteint : vitesses réelles plafonnées ({details}).")
    machine_max = _num(ps.get("machine_max_speed_x"))
    too_fast = [k for k, _, _ in FEATURES.values() if machine_max and _num(ps.get(k)) > machine_max]
    if too_fast:
        out.append(f"Vitesses au-dessus du maximum machine ({machine_max:g} mm/s) : {too_fast}.")
    if _num(ps.get("slow_down_for_layer_cooling"), 1) and _num(ps.get("slow_down_layer_time"), 1) == 0:
        out.append("slow_down_layer_time = 0 : pas de ralentissement sur les petites couches "
                   "(cheminées, pointes, détails fins risquent de fondre).")
    if not _num(ps.get("slow_down_for_layer_cooling"), 1):
        out.append("Ralentissement pour refroidissement désactivé (slow_down_for_layer_cooling = 0).")
    nozzle = _num(ps.get("nozzle_diameter"), 0.4)
    layer = _num(ps.get("layer_height"))
    if layer > nozzle * 0.75:
        out.append(f"Couche de {layer:g} mm trop épaisse pour une buse de {nozzle:g} mm (max conseillé {nozzle * 0.75:g}).")
    if _num(ps.get("wall_loops"), 2) < 2:
        out.append("Une seule paroi : pièce fragile et surfaces irrégulières.")
    ftype = ps.get("filament_type")
    ftype = (ftype[0] if isinstance(ftype, list) and ftype else ftype) or ""
    if ftype.upper() in ("ABS", "ASA", "PC", "PA") and _num(ps.get("fan_max_speed"), 0) > 60:
        out.append(f"{ftype} avec ventilateur jusqu'à {_num(ps.get('fan_max_speed')):g} % : risque de délaminage "
                   "(fermer le capot de la P1S, ventilation réduite).")
    if ftype.upper() == "TPU":
        out.append("TPU : à charger par la bobine externe, pas par l'AMS.")
    return out


def check_3mf(path: str) -> dict:
    ps = threemf.get_settings(path)
    return {"filament_max_volumetric_speed": _num(ps.get("filament_max_volumetric_speed")),
            "flow": flow_check(ps), "warnings": warnings(ps)}
