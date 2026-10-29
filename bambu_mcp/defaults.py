"""User defaults (printer, build plate, filament), chosen on first use."""
from . import config, materials, presets


def current() -> dict:
    return {"setup_needed": config.setup_needed(), "machine": config.default_machine(),
            "process": config.default_process(), "bed_type": config.load().get("default_bed_type"),
            "filament": config.default_filament()}


def options() -> dict:
    """Available choices: printers (system and user machine presets) and build plates."""
    machines = [r["name"] for r in presets.list_presets("machine", "all")
                if r["source"] == "user" or r["name"].startswith("Bambu Lab")]
    return {"machines": machines, "bed_types": list(materials.BED_TYPES)}


def _filament(name: str, machine: str) -> str:
    """Filament preset for `machine`, from a preset or material name ("PLA Matte")."""
    try:
        return presets.for_machine("filament", name, machine)
    except KeyError:
        _, info = materials.find(name)  # KeyError listing the materials if unknown
        return presets.for_machine("filament", info["filament"], machine)


def configure(machine: str | None = None, bed_type: str | None = None, filament: str | None = None) -> dict:
    """Validate then save the given values in config.json; the others stay unchanged."""
    updates: dict = {}
    if machine:
        name = presets.canonical("machine", machine)
        updates.update({"default_machine": name, "default_process": presets.standard_process(name)})
    target = updates.get("default_machine") or config.default_machine()
    if bed_type:
        beds = {b.lower(): b for b in materials.BED_TYPES}
        if bed_type.lower() not in beds:
            raise ValueError(f"Unknown build plate {bed_type!r}: {list(materials.BED_TYPES)}")
        updates["default_bed_type"] = beds[bed_type.lower()]
    # A saved filament follows a printer change.
    if filament or (machine and config.default_filament()):
        updates["default_filament"] = _filament(filament or config.default_filament(), target)
    if not updates and config.setup_needed():
        updates["default_machine"] = target  # Confirms the default printer as is.
    if updates:
        config.save(updates)
    return {**current(), "saved": updates}
