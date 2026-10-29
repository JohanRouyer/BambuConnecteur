"""Valeurs par défaut de l'utilisateur (imprimante, plateau, filament), choisies à la première utilisation."""
from . import config, materials, presets


def current() -> dict:
    return {"setup_needed": config.setup_needed(), "machine": config.default_machine(),
            "process": config.default_process(), "bed_type": config.load().get("default_bed_type"),
            "filament": config.default_filament()}


def options() -> dict:
    """Choix possibles : imprimantes (presets machine système et utilisateur) et plateaux."""
    machines = [r["name"] for r in presets.list_presets("machine", "all")
                if r["source"] == "user" or r["name"].startswith("Bambu Lab")]
    return {"machines": machines, "bed_types": list(materials.BED_TYPES)}


def _filament(name: str, machine: str) -> str:
    """Preset filament pour `machine`, à partir d'un nom de preset ou de matériau (« PLA Matte »)."""
    try:
        return presets.for_machine("filament", name, machine)
    except KeyError:
        _, info = materials.find(name)  # KeyError avec la liste des matériaux si inconnu
        return presets.for_machine("filament", info["filament"], machine)


def configure(machine: str | None = None, bed_type: str | None = None, filament: str | None = None) -> dict:
    """Valide puis enregistre les valeurs données dans config.json ; les autres restent inchangées."""
    updates: dict = {}
    if machine:
        name = presets.canonical("machine", machine)
        updates.update({"default_machine": name, "default_process": presets.standard_process(name)})
    target = updates.get("default_machine") or config.default_machine()
    if bed_type:
        beds = {b.lower(): b for b in materials.BED_TYPES}
        if bed_type.lower() not in beds:
            raise ValueError(f"Plateau inconnu {bed_type!r} : {list(materials.BED_TYPES)}")
        updates["default_bed_type"] = beds[bed_type.lower()]
    # Un filament déjà enregistré suit le changement d'imprimante.
    if filament or (machine and config.default_filament()):
        updates["default_filament"] = _filament(filament or config.default_filament(), target)
    if not updates and config.setup_needed():
        updates["default_machine"] = target  # Confirme l'imprimante par défaut telle quelle.
    if updates:
        config.save(updates)
    return {**current(), "saved": updates}
