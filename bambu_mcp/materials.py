"""Conseils matériaux pour la P1S (buse acier inox 0.4 d'origine, caisson fermé non chauffé)."""
from . import presets

# plate : plateaux conseillés, du meilleur au moins bon (noms de la CLI Bambu Studio).
MATERIALS = {
    "PLA": {"filament": "Bambu PLA Basic @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
            "enclosure": "Capot vitré retiré ou porte entrouverte : la chaleur du caisson bouche la buse (heat creep).",
            "ams": True, "notes": ["Matériau le plus simple ; idéal pour prototypes et pièces déco."]},
    "PLA Matte": {"filament": "Bambu PLA Matte @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
                  "enclosure": "Capot retiré ou porte entrouverte.", "ams": True,
                  "notes": ["Masque bien les lignes de couche ; un peu plus cassant que le PLA Basic."]},
    "PLA Silk": {"filament": "Bambu PLA Silk+ @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Cool Plate"],
                 "enclosure": "Capot retiré ou porte entrouverte.", "ams": True,
                 "notes": ["Aspect brillant : vitesses modérées sur les parois extérieures pour un rendu uniforme."]},
    "PLA-CF": {"filament": "Bambu PLA-CF @BBL X1C", "plate": ["Textured PEI Plate", "Cool Plate"],
               "enclosure": "Capot retiré ou porte entrouverte.", "ams": True, "abrasive": True,
               "notes": ["Rigide et mat ; chargé en fibres de carbone."]},
    "PETG": {"filament": "Bambu PETG HF @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "Engineering Plate"],
             "enclosure": "Porte fermée possible ; capot entrouvert si la buse bouche.", "ams": True,
             "notes": ["Sur plateau lisse (High Temp / PEI lisse), mettre de la colle : sinon il arrache la surface.",
                       "Plus résistant à la chaleur et aux chocs que le PLA ; un peu de fils (stringing)."]},
    "PETG-CF": {"filament": "Bambu PETG-CF @BBL X1C 0.4 nozzle", "plate": ["Textured PEI Plate", "Engineering Plate"],
                "enclosure": "Porte fermée.", "ams": True, "abrasive": True, "dry": True,
                "notes": ["Sécher avant impression (absorbe l'humidité)."]},
    "ABS": {"filament": "Bambu ABS @BBL P1S 0.4 nozzle", "plate": ["Textured PEI Plate", "High Temp Plate"],
            "enclosure": "Porte ET capot fermés ; préchauffer le caisson 5-10 min avec le plateau chaud.",
            "ams": True, "brim": True,
            "notes": ["Se rétracte en refroidissant : bordure sur les grandes pièces, éviter les courants d'air.",
                      "Dégage des odeurs (styrène) : pièce aérée."]},
    "ASA": {"filament": "Bambu ASA @BBL X1C 0.4 nozzle", "plate": ["Textured PEI Plate", "High Temp Plate"],
            "enclosure": "Porte ET capot fermés.", "ams": True, "brim": True,
            "notes": ["Comme l'ABS mais résiste aux UV : pièces d'extérieur."]},
    "PC": {"filament": "Bambu PC @BBL P1S", "plate": ["Textured PEI Plate", "Engineering Plate"],
           "enclosure": "Porte ET capot fermés ; préchauffage du caisson indispensable.", "ams": True,
           "brim": True, "dry": True,
           "notes": ["Le caisson de la P1S n'est pas chauffé : grandes pièces en PC sujettes au gauchissement."]},
    "PA-CF": {"filament": "Bambu PA6-CF @BBL X1C", "plate": ["Textured PEI Plate", "Engineering Plate"],
              "enclosure": "Porte ET capot fermés.", "ams": False, "abrasive": True, "dry": True, "brim": True,
              "notes": ["Très hygroscopique : sécher (80 °C, 8 h) et imprimer depuis une boîte sèche."]},
    "TPU": {"filament": "Bambu TPU 95A HF @BBL P1S", "plate": ["Textured PEI Plate", "Cool Plate"],
            "enclosure": "Capot retiré ou porte entrouverte.", "ams": False,
            "notes": ["Bobine externe uniquement (sauf « TPU for AMS ») ; souple, vitesses basses.",
                      "Éviter les rétractions longues ; pas de supports si possible."]},
}

_ALIASES = {"PLA BASIC": "PLA", "PETG HF": "PETG", "PA": "PA-CF", "PA6-CF": "PA-CF", "TPU 95A": "TPU",
            "SILK": "PLA Silk", "MATTE": "PLA Matte"}


def find(material: str) -> tuple[str, dict]:
    key = material.strip()
    upper = {k.upper(): k for k in MATERIALS}
    name = upper.get(key.upper()) or _ALIASES.get(key.upper())
    if not name:
        raise KeyError(f"Matériau inconnu {material!r} : {list(MATERIALS)}")
    return name, MATERIALS[name]


def guide(material: str | None = None, filament: str | None = None) -> dict:
    """Conseils P1S pour un matériau, avec les températures du preset filament."""
    if not material:
        return {"materials": {k: v["filament"] for k, v in MATERIALS.items()}}
    name, info = find(material)
    preset = filament or info["filament"]
    cfg = presets.resolve("filament", preset)
    first = lambda k: (cfg.get(k) or [None])[0] if isinstance(cfg.get(k), list) else cfg.get(k)  # noqa: E731
    out = {"material": name, "filament_preset": preset, "plates": info["plate"], "enclosure": info["enclosure"],
           "ams_ok": info["ams"], "nozzle_c": first("nozzle_temperature"),
           # 0 °C = plateau non prévu pour ce filament.
           "bed_c": {p: t for p, t in {"Textured PEI Plate": first("textured_plate_temp"),
                                       "Cool Plate": first("cool_plate_temp"),
                                       "Engineering Plate": first("eng_plate_temp"),
                                       "High Temp Plate": first("hot_plate_temp")}.items() if t and t != "0"},
           "max_volumetric_mm3_s": first("filament_max_volumetric_speed"),
           "fan_pct": [first("fan_min_speed"), first("fan_max_speed")], "notes": list(info["notes"])}
    if info.get("abrasive"):
        out["notes"].insert(0, "ABRASIF : buse en acier trempé obligatoire (la buse inox d'origine de la P1S s'use "
                               "en quelques bobines).")
    if info.get("dry"):
        out["notes"].append("Sécher la bobine avant usage.")
    return out
