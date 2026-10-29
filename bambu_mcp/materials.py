"""Material advice (tuned on a P1S: stock 0.4 stainless steel nozzle, unheated enclosure)."""
from . import config, presets

# Bambu build plates (CLI names) -> filament temperature setting.
BED_TYPES = {"Textured PEI Plate": "textured_plate_temp", "Cool Plate": "cool_plate_temp",
             "Engineering Plate": "eng_plate_temp", "High Temp Plate": "hot_plate_temp",
             "Supertack Plate": "supertack_plate_temp"}

# plate: recommended build plates, best first (Bambu Studio CLI names).
MATERIALS = {
    "PLA": {"filament": "Bambu PLA Basic @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
            "enclosure": "Glass lid off or door ajar: enclosure heat clogs the nozzle (heat creep).",
            "ams": True, "notes": ["Easiest material; ideal for prototypes and decorative parts."]},
    "PLA Matte": {"filament": "Bambu PLA Matte @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
                  "enclosure": "Lid off or door ajar.", "ams": True,
                  "notes": ["Hides layer lines well; slightly more brittle than PLA Basic."]},
    "PLA Silk": {"filament": "Bambu PLA Silk+ @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
                 "enclosure": "Lid off or door ajar.", "ams": True,
                 "notes": ["Glossy look: moderate outer wall speeds for an even finish."]},
    "PLA-CF": {"filament": "Bambu PLA-CF @BBL X1C", "plate": ["Textured PEI Plate", "Cool Plate"],
               "enclosure": "Lid off or door ajar.", "ams": True, "abrasive": True,
               "notes": ["Stiff and matte; carbon-fiber filled."]},
    "PETG": {"filament": "Bambu PETG HF @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Engineering Plate"],
             "enclosure": "Door can stay closed; open the lid a little if the nozzle clogs.", "ams": True,
             "notes": ["On a smooth plate (High Temp / smooth PEI), use glue: otherwise it tears the surface.",
                       "More heat and impact resistant than PLA; some stringing."]},
    "PETG-CF": {"filament": "Bambu PETG-CF @BBL X1C 0.4 nozzle", "plate": ["Textured PEI Plate", "Engineering Plate"],
                "enclosure": "Door closed.", "ams": True, "abrasive": True, "dry": True,
                "notes": ["Dry before printing (absorbs moisture)."]},
    "ABS": {"filament": "Bambu ABS @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "High Temp Plate"],
            "enclosure": "Door AND lid closed; preheat the enclosure 5-10 min with the bed hot.",
            "ams": True, "brim": True,
            "notes": ["Shrinks as it cools: brim on large parts, avoid drafts.",
                      "Gives off fumes (styrene): ventilate the room."]},
    "ASA": {"filament": "Bambu ASA @BBL X1C 0.4 nozzle", "plate": ["Textured PEI Plate", "High Temp Plate"],
            "enclosure": "Door AND lid closed.", "ams": True, "brim": True,
            "notes": ["Like ABS but UV resistant: outdoor parts."]},
    "PC": {"filament": "Bambu PC @BBL P1S", "plate": ["Textured PEI Plate", "Engineering Plate"],
           "enclosure": "Door AND lid closed; preheating the enclosure is a must.", "ams": True,
           "brim": True, "dry": True,
           "notes": ["Unheated enclosures (P1S, X1C) make large PC parts prone to warping."]},
    "PA-CF": {"filament": "Bambu PA6-CF @BBL X1C", "plate": ["Textured PEI Plate", "Engineering Plate"],
              "enclosure": "Door AND lid closed.", "ams": False, "abrasive": True, "dry": True, "brim": True,
              "notes": ["Very hygroscopic: dry it (80 °C, 8 h) and print from a dry box."]},
    "TPU": {"filament": "Bambu TPU 95A HF @BBL P1S", "plate": ["Textured PEI Plate", "Cool Plate"],
            "enclosure": "Lid off or door ajar.", "ams": False,
            "notes": ["External spool only (except \"TPU for AMS\"); flexible, slow speeds.",
                      "Avoid long retractions; no supports if possible."]},
}

_ALIASES = {"PLA BASIC": "PLA", "PETG HF": "PETG", "PA": "PA-CF", "PA6-CF": "PA-CF", "TPU 95A": "TPU",
            "SILK": "PLA Silk", "MATTE": "PLA Matte"}


def find(material: str) -> tuple[str, dict]:
    key = material.strip()
    upper = {k.upper(): k for k in MATERIALS}
    name = upper.get(key.upper()) or _ALIASES.get(key.upper())
    if not name:
        raise KeyError(f"Unknown material {material!r}: {list(MATERIALS)}")
    return name, MATERIALS[name]


def guide(material: str | None = None, filament: str | None = None) -> dict:
    """Advice for a material, with the temperatures of its filament preset for the default printer."""
    if not material:
        return {"materials": {k: v["filament"] for k, v in MATERIALS.items()}}
    name, info = find(material)
    preset = filament or presets.for_machine("filament", info["filament"], config.default_machine())
    cfg = presets.resolve("filament", preset)
    first = lambda k: (cfg.get(k) or [None])[0] if isinstance(cfg.get(k), list) else cfg.get(k)  # noqa: E731
    out = {"material": name, "filament_preset": preset, "plates": info["plate"], "enclosure": info["enclosure"],
           "ams_ok": info["ams"], "nozzle_c": first("nozzle_temperature"),
           # 0 °C = build plate not meant for this filament.
           "bed_c": {p: t for p, t in ((p, first(k)) for p, k in BED_TYPES.items()) if t and t != "0"},
           "max_volumetric_mm3_s": first("filament_max_volumetric_speed"),
           "fan_pct": [first("fan_min_speed"), first("fan_max_speed")], "notes": list(info["notes"])}
    if info.get("abrasive"):
        out["notes"].insert(0, "ABRASIVE: hardened steel nozzle required (a stock stainless steel nozzle wears out "
                               "within a few spools).")
    if info.get("dry"):
        out["notes"].append("Dry the spool before use.")
    return out
