"""MCP server: gives Claude access to Bambu presets, projects, slicer and printer."""
import functools
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis, config, defaults, geometry, history, materials, prepare, presets, printer, slicer, threemf

Kind = Literal["process", "filament", "machine"]
Goal = Literal["quality", "balanced", "speed", "strength", "light"]
EXPECTED_ERRORS = (KeyError, ValueError, OSError, TimeoutError, RecursionError)


def readable_errors(fn):
    """Pass the error message through as is (otherwise the SDK replaces it with a generic one)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except EXPECTED_ERRORS as exc:
            message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            raise ToolError(str(message)) from exc
    return wrapper


class _Server(MCPServer):
    def tool(self, *args, **kwargs):
        register = super().tool(*args, **kwargs)
        return lambda fn: register(readable_errors(fn))


mcp = _Server(
    "bambu-studio",
    instructions=(
        "Local access to Bambu Studio and the user's default Bambu Lab printer (first use: when "
        "connector_info.setup_needed is true, ask for the printer, build plate and filament, then call "
        "setup_defaults). Setting values are Bambu strings (\"0.2\", \"15%\", \"1\"/\"0\"); a single value "
        "is copied to every variant. Recommended flow: read the preset or project, suggest changes, "
        "slice to compare time and weight, and only then save. Bambu Studio must be restarted to see "
        "a modified preset. The printer tool is read-only."
    ),
)


@mcp.tool()
def list_presets(kind: Kind, source: Literal["all", "user", "system"] = "user",
                 printer_name: str | None = "default", search: str | None = None) -> list[dict]:
    """List presets (process, filament or machine). `printer_name` keeps the compatible ones
    ("default" = the default printer); pass null to see everything. `search`: words to find in the name."""
    if printer_name == "default":
        printer_name = config.default_machine()
    return presets.list_presets(kind, source, printer_name, search)


@mcp.tool()
def get_preset(kind: Kind, name: str, key_filter: str | None = None,
               only_overrides: bool = False) -> dict:
    """Settings of a preset, inheritance resolved. `key_filter`: keywords of setting names
    (e.g. "speed accel"). `only_overrides`: only what this preset changes from its parent."""
    source, path, data = presets.find(kind, name)
    values = presets.overrides(kind, name) if only_overrides else presets.resolve(kind, name)
    if key_filter:
        words = key_filter.lower().split()
        values = {k: v for k, v in values.items() if any(w in k.lower() for w in words)}
    return {"name": name, "source": source, "inherits": data.get("inherits"), "file": str(path),
            "count": len(values), "settings": values}


@mcp.tool()
def compare_presets(kind: Kind, preset_a: str, preset_b: str) -> list[dict]:
    """Settings that differ between two presets of the same type."""
    return presets.diff(kind, preset_a, preset_b)


@mcp.tool()
def save_preset(kind: Kind, name: str, settings: dict, parent: str | None = None) -> dict:
    """Create (with `parent`) or update a user preset. The old file is backed up in backups/.
    Use only once the user has agreed to the changes."""
    return presets.save_user_preset(kind, name, settings, parent)


@mcp.tool()
def inspect_3mf(path: str) -> dict:
    """Summary of a 3MF file: origin, presets used, objects and their own settings, plates,
    and slicing results if it has any."""
    return threemf.inspect(path)


@mcp.tool()
def get_3mf_settings(path: str, key_filter: str | None = None) -> dict:
    """Every setting of a Bambu 3MF project (or those whose name contains one of the `key_filter` words)."""
    return threemf.get_settings(path, key_filter)


@mcp.tool()
def edit_3mf(path: str, settings: dict | None = None, object_settings: dict | None = None,
             output_path: str | None = None) -> dict:
    """Write an edited copy of a 3MF project (by default <name>_claude.3mf next to the original).
    `settings`: project settings. `object_settings`: {object name or id: {setting: value}}."""
    return threemf.edit(path, settings, object_settings, output_path)


@mcp.tool()
def slice_model(models: list[str], machine: str | None = None, process: str | None = None,
                filaments: list[str] | None = None, process_overrides: dict | None = None,
                filament_overrides: dict | None = None, plate: int = 0,
                bed_type: str | None = None, orient: bool = False, arrange: bool = False) -> dict:
    """Slice with Bambu Studio and return time, weight, time per line type and warnings.
    Without presets, a Bambu 3MF keeps its own settings and the overrides apply to it (the original
    is not modified); a project made for another printer is moved to the default printer.
    An STL or geometry-only 3MF becomes a complete Bambu project (result.3mf), with `machine`
    (+ process, filaments) or else the default presets (setup_defaults).
    `filaments` alone on a project: replaces its filament, keeping the project's print settings.
    `plate` 0 = every plate in a single result.3mf. `bed_type` e.g. "Textured PEI Plate"."""
    return slicer.run(models, machine, process, filaments, process_overrides, filament_overrides,
                      plate, bed_type, orient, arrange)


@mcp.tool()
def compare_slices(models: list[str], variants: dict[str, dict], include_original: bool = True,
                   machine: str | None = None, process: str | None = None,
                   filaments: list[str] | None = None, plate: int = 0,
                   bed_type: str | None = None) -> dict:
    """Slice several variants IN PARALLEL in a single call: {name: {setting: value}}.
    Returns time, weight (total and per plate), % difference from the original and checks for each
    variant. On a 3MF without `machine`, settings apply to the project, moved to the default printer
    (the original is not modified). `filaments` alone: the project's filament is replaced (preset,
    e.g. from material_guide). `plate` 0 = every plate in a single result.3mf per variant."""
    return slicer.compare(models, variants, include_original, machine, process, filaments, plate, bed_type)


@mcp.tool()
def optimize(models: list[str], goal: Goal, machine: str | None = None, process: str | None = None,
             filaments: list[str] | None = None, plate: int = 0, bed_type: str | None = None,
             compare_all: bool = True) -> dict:
    """Ready-made recipes (accelerations brought within the printer's limits): slices the original
    and the 5 goals in parallel, then picks the `goal` variant. `compare_all` false: only the original
    and `goal`. Leave `plate` at 0: a single result.3mf per variant with every plate, per-plate
    details included. `filaments` (preset, e.g. from material_guide): the user's chosen filament,
    applied to the project."""
    return slicer.optimize(models, goal, machine, process, filaments, plate, bed_type, compare_all)


@mcp.tool()
def check_settings(path: str) -> dict:
    """Check a 3MF project without slicing: volumetric flow per line type (actual speed when the
    filament's max flow caps it), machine speeds, cooling, pitfalls per material."""
    return analysis.check_3mf(path)


@mcp.tool()
def analyze_model(path: str) -> dict:
    """Geometry of an STL or 3MF: dimensions, volume, fit on the default printer, footprint,
    overhangs and bridges for 6 orientations, best orientation and advice (supports, brim)."""
    return geometry.analyze(path)


@mcp.tool()
def material_guide(material: str | None = None, filament: str | None = None) -> dict:
    """Advice per material (PLA, PETG, ABS, ASA, PC, TPU, PA-CF, …): filament preset for the default
    printer, build plates and temperatures, lid / door, AMS, nozzle, drying. Without `material`: the list."""
    return materials.guide(material, filament)


@mcp.tool()
def prepare_print(models: list[str], material: str = "PLA", goal: Goal = "balanced",
                  copies: int = 1, orientation: Literal["auto", "as_is"] = "auto",
                  supports: Literal["auto", "on", "off"] = "auto", bed_type: str | None = None,
                  filament: str | None = None, extra_settings: dict | None = None) -> dict:
    """From STL / 3MF to a print-ready project in one call: analysis, best orientation, material
    presets, build plate, supports and brim when needed, copies arranged, slice. Returns time, weight,
    decisions made, warnings and the result.3mf to open in Bambu Studio."""
    return prepare.prepare(models, material, goal, copies, orientation, supports, bed_type,
                           filament, extra_settings)


@mcp.tool()
def slice_history(limit: int = 20, search: str | None = None) -> list[dict]:
    """Latest slices (newest first): models, presets, changed settings, time, weight, number of
    checks and result.3mf. `search`: words from the model name or the label."""
    return history.read(limit, search)


@mcp.tool()
def printer_status(include_raw: bool = False) -> dict:
    """Printer status over the local network: print job, temperatures, fans, AMS, HMS errors."""
    return printer.status(include_raw=include_raw)


@mcp.tool()
def setup_defaults(machine: str | None = None, bed_type: str | None = None,
                   filament: str | None = None) -> dict:
    """The user's defaults, to set on first use (`setup_needed`).
    No argument: current values and available choices (printers, build plates).
    With arguments: validates and saves them. `machine`: exact machine preset
    (e.g. "Bambu Lab A1 0.4 nozzle"; the standard process follows). `filament`: preset or material
    (e.g. "PLA Matte"), adapted to the printer."""
    if not (machine or bed_type or filament):
        return {**defaults.current(), "options": defaults.options()}
    return defaults.configure(machine, bed_type, filament)


@mcp.tool()
def connector_info() -> dict:
    """Paths used by the connector and configuration status. `setup_needed` true: first use,
    ask for the printer, build plate and filament, then call setup_defaults."""
    p = config.printer()
    return {"setup_needed": config.setup_needed(), "defaults": defaults.current(),
            "bambu_studio": str(config.executable()), "exists": config.executable().exists(),
            "user_presets": str(config.user_presets_dir()), "output_dir": str(config.output_dir()),
            "config_file": str(config.CONFIG_FILE),
            "printer_configured": all(p.get(k) for k in ("host", "serial", "access_code")),
            "bambu_studio_running": config.bambu_studio_running()}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
