"""MCP server: gives Claude access to Bambu presets, projects, slicer and printer."""
import functools
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import analysis, config, defaults, geometry, history, materials, prepare, presets, printer, slicer, threemf

Kind = Literal["process", "filament", "machine"]
Goal = Literal["quality", "balanced", "speed", "strength", "light"]
EXPECTED_ERRORS = (KeyError, ValueError, OSError, TimeoutError, RecursionError)

# Behavior hints for clients: reads only, writes new files (output/, config.json), or overwrites user files.
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
OUTPUT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

KindArg = Annotated[Kind, Field(description='Preset type: "process" (print settings), "filament" or "machine" (printer).')]
Models = Annotated[list[str], Field(description="Absolute paths of the STL or 3MF files to slice together.")]
Machine = Annotated[str | None, Field(description='Machine preset name, e.g. "Bambu Lab P1S 0.4 nozzle". '
                                                  "Omit to keep a 3MF project's own settings or use the defaults.")]
Process = Annotated[str | None, Field(description='Process preset name, e.g. "0.20mm Standard @BBL X1C". '
                                                  "Needs `machine`.")]
Filaments = Annotated[list[str] | None, Field(description="Filament preset names, one per slot "
                                                          '(e.g. "Bambu PLA Matte @BBL P1S 0.4 nozzle"). Alone on '
                                                          "a 3MF project, replaces its filament.")]
Plate = Annotated[int, Field(description="Plate number to slice; 0 = every plate in a single result.3mf.", ge=0)]
BedType = Annotated[str | None, Field(description='Build plate, e.g. "Textured PEI Plate", "Cool Plate", '
                                                  '"High Temp Plate". Omit for the usual plate when the filament '
                                                  "suits it.")]
Path3mf = Annotated[str, Field(description="Absolute path of a Bambu 3MF project.")]


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


@mcp.tool(title="List presets", annotations=READ)
def list_presets(kind: KindArg,
                 source: Annotated[Literal["all", "user", "system"], Field(
                     description='"user" (presets the user saved), "system" (Bambu presets) or "all".')] = "user",
                 printer_name: Annotated[str | None, Field(
                     description='Keep only presets compatible with this machine preset; "default" = the '
                                 "user's default printer, null = every printer.")] = "default",
                 search: Annotated[str | None, Field(
                     description='Words that must all appear in the preset name, e.g. "PLA Matte".')] = None,
                 ) -> list[dict]:
    """List Bambu Studio presets of one type, with their source and parent. Read-only.
    Use it to find an exact preset name before get_preset, compare_presets or slicing; use
    material_guide instead to get the recommended filament preset for a material."""
    if printer_name == "default":
        printer_name = config.default_machine()
    return presets.list_presets(kind, source, printer_name, search)


@mcp.tool(title="Read a preset", annotations=READ)
def get_preset(kind: KindArg,
               name: Annotated[str, Field(description="Exact preset name, as returned by list_presets.")],
               key_filter: Annotated[str | None, Field(
                   description='Keywords of setting names to keep, e.g. "speed accel". Omit for all settings.')] = None,
               only_overrides: Annotated[bool, Field(
                   description="True: only the settings this preset changes from its parent.")] = False,
               ) -> dict:
    """Read the settings of one preset, with inheritance resolved (values as Bambu strings). Read-only.
    Use it to inspect a single preset; use compare_presets to see only the differences between two,
    and get_3mf_settings for the settings stored in a 3MF project. Fails if the name is unknown and
    lists close names."""
    source, path, data = presets.find(kind, name)
    values = presets.overrides(kind, name) if only_overrides else presets.resolve(kind, name)
    if key_filter:
        words = key_filter.lower().split()
        values = {k: v for k, v in values.items() if any(w in k.lower() for w in words)}
    return {"name": name, "source": source, "inherits": data.get("inherits"), "file": str(path),
            "count": len(values), "settings": values}


@mcp.tool(title="Compare two presets", annotations=READ)
def compare_presets(kind: KindArg,
                    preset_a: Annotated[str, Field(description="Exact name of the first preset.")],
                    preset_b: Annotated[str, Field(description="Exact name of the second preset, of the same type.")],
                    ) -> list[dict]:
    """Compare two presets of the same type and return only the settings whose values differ
    (setting, value in A, value in B), inheritance resolved. Read-only.
    Use it to see what a user preset changes from a Bambu preset, or how two profiles differ; use
    get_preset to read one preset in full. Fails if either name is unknown."""
    return presets.diff(kind, preset_a, preset_b)


@mcp.tool(title="Save a user preset", annotations=WRITE)
def save_preset(kind: KindArg,
                name: Annotated[str, Field(description="Name of the user preset to create or update.")],
                settings: Annotated[dict, Field(
                    description='Settings to write, as Bambu strings: {"layer_height": "0.16", '
                                '"sparse_infill_density": "15%"}. Unknown setting names are rejected.')],
                parent: Annotated[str | None, Field(
                    description="Preset to inherit from when creating a new one (e.g. a system preset). "
                                "Omit to update an existing user preset.")] = None,
                ) -> dict:
    """Create or update a user preset in Bambu Studio's user folder. Overwrites the existing user
    preset of that name; the previous file is backed up in backups/ first.
    Only call it once the user has agreed to the changes, after slicing to compare them
    (compare_slices). Bambu Studio must be restarted to show the change."""
    return presets.save_user_preset(kind, name, settings, parent)


@mcp.tool(title="Inspect a 3MF file", annotations=READ)
def inspect_3mf(path: Annotated[str, Field(description="Absolute path of a .3mf file.")]) -> dict:
    """Summarize a 3MF file: whether it is a full Bambu project or geometry only, the printer and
    presets it was made with, its objects and their own settings, its plates, and slicing results if
    it has any. Read-only. Use it first on any 3MF; use get_3mf_settings for the full list of project
    settings and analyze_model for the geometry."""
    return threemf.inspect(path)


@mcp.tool(title="Read 3MF project settings", annotations=READ)
def get_3mf_settings(path: Path3mf,
                     key_filter: Annotated[str | None, Field(
                         description='Keywords of setting names to keep, e.g. "wall infill". Omit for all.')] = None,
                     ) -> dict:
    """Read the print settings stored in a Bambu 3MF project (project_settings.config), as Bambu
    strings. Read-only. Use it to see the values a project will print with; use inspect_3mf for a
    summary and check_settings for problems. Fails on a 3MF without Bambu settings."""
    return threemf.get_settings(path, key_filter)


@mcp.tool(title="Write an edited 3MF copy", annotations=OUTPUT)
def edit_3mf(path: Path3mf,
             settings: Annotated[dict | None, Field(
                 description='Project settings to change, as Bambu strings: {"wall_loops": "3"}.')] = None,
             object_settings: Annotated[dict | None, Field(
                 description='Per-object settings: {"object name or id": {"setting": "value"}}.')] = None,
             output_path: Annotated[str | None, Field(
                 description="Where to write the copy. Default: <name>_claude.3mf next to the original. "
                             "Passing the original's path replaces it: only with the user's agreement.")] = None,
             ) -> dict:
    """Write a copy of a 3MF project with changed settings, without slicing. The original is left
    untouched unless output_path is its own path. Use it to hand the user an edited project; to
    measure the effect of settings, use slice_model or compare_slices instead (they never modify
    the original)."""
    return threemf.edit(path, settings, object_settings, output_path)


@mcp.tool(title="Slice a model", annotations=OUTPUT)
def slice_model(models: Models, machine: Machine = None, process: Process = None,
                filaments: Filaments = None,
                process_overrides: Annotated[dict | None, Field(
                    description='Print settings to change for this slice: {"layer_height": "0.16"}.')] = None,
                filament_overrides: Annotated[dict | None, Field(
                    description='Filament settings to change: {"nozzle_temperature": "225"}.')] = None,
                plate: Plate = 0, bed_type: BedType = None,
                orient: Annotated[bool, Field(description="Let Bambu Studio auto-orient the objects.")] = False,
                arrange: Annotated[bool, Field(description="Let Bambu Studio auto-arrange the objects.")] = False,
                ) -> dict:
    """Slice once with the real Bambu Studio engine and return print time, filament weight, time per
    line type, warnings and the path of the sliced result.3mf (written under output/; originals are
    never modified). An identical slice comes back from the cache.
    A Bambu 3MF keeps its own settings (moved to the default printer if made for another); an STL
    gets `machine`/`process`/`filaments` or the user's defaults. Use compare_slices to try several
    settings at once, optimize for ready-made goals, prepare_print to go from a raw STL to a project."""
    return slicer.run(models, machine, process, filaments, process_overrides, filament_overrides,
                      plate, bed_type, orient, arrange)


@mcp.tool(title="Compare setting variants", annotations=OUTPUT)
def compare_slices(models: Models,
                   variants: Annotated[dict[str, dict], Field(
                       description='Variants to slice: {"variant name": {"setting": "value"}}, e.g. '
                                   '{"thin walls": {"wall_loops": "2"}, "strong": {"wall_loops": "4"}}.')],
                   include_original: Annotated[bool, Field(
                       description="Also slice the unchanged model as the reference.")] = True,
                   machine: Machine = None, process: Process = None, filaments: Filaments = None,
                   plate: Plate = 0, bed_type: BedType = None) -> dict:
    """Slice several setting variants in parallel in one call and compare them: time, weight (total
    and per plate), % difference from the original and checks for each. Results are written under
    output/; the original is never modified. Use it to test your own settings; use optimize for the
    5 ready-made goals and slice_model for a single slice."""
    return slicer.compare(models, variants, include_original, machine, process, filaments, plate, bed_type)


@mcp.tool(title="Optimize for a goal", annotations=OUTPUT)
def optimize(models: Models,
             goal: Annotated[Goal, Field(
                 description='"quality" (fine layers, slower walls), "balanced", "speed", "strength" '
                             '(more walls and infill) or "light" (least filament).')],
             machine: Machine = None, process: Process = None, filaments: Filaments = None,
             plate: Plate = 0, bed_type: BedType = None,
             compare_all: Annotated[bool, Field(
                 description="True: slice all 5 goals for comparison; false: only the original and `goal`.")] = True,
             ) -> dict:
    """Slice the original and ready-made recipes (quality, balanced, speed, strength, light) in
    parallel, with accelerations kept within the printer's limits, and return the comparison plus the
    recommended `goal` variant and its result.3mf (under output/; the original is never modified).
    Use it to answer "how should I print this"; pass the user's chosen filament preset in `filaments`.
    Use compare_slices for custom settings."""
    return slicer.optimize(models, goal, machine, process, filaments, plate, bed_type, compare_all)


@mcp.tool(title="Check project settings", annotations=READ)
def check_settings(path: Path3mf) -> dict:
    """Check a 3MF project's settings without slicing: volumetric flow per line type against the
    filament's max flow (and the speed actually reached when capped), speeds above the machine's
    limits, cooling and per-material pitfalls. Read-only. Use it before slicing a project;
    slice_model reports the same checks on its result."""
    return analysis.check_3mf(path)


@mcp.tool(title="Analyze geometry", annotations=READ)
def analyze_model(path: Annotated[str, Field(description="Absolute path of an STL or 3MF file.")]) -> dict:
    """Analyze the geometry of an STL or 3MF: dimensions, volume, whether it fits the default
    printer's bed, footprint, overhangs and bridges for 6 orientations, the best orientation and
    support/brim advice. Read-only and fast (no slicing). Use it first on any model; STEP and OBJ
    files are not supported."""
    return geometry.analyze(path)


@mcp.tool(title="Material guide", annotations=READ)
def material_guide(material: Annotated[str | None, Field(
                       description='Material name: "PLA", "PLA Matte", "PETG", "ABS", "ASA", "PC", "TPU", '
                                   '"PA-CF"... Omit to list the materials.')] = None,
                   filament: Annotated[str | None, Field(
                       description="Exact filament preset to describe instead of the material's default one.")] = None,
                   ) -> dict:
    """Give printing advice for a material on the default printer: the filament preset to use,
    suitable build plates and temperatures, enclosure (lid/door), AMS compatibility, nozzle and
    drying notes. Read-only. Use it to pick the filament preset passed to slicing tools; use
    list_presets to search for a specific brand."""
    return materials.guide(material, filament)


@mcp.tool(title="Prepare a print", annotations=OUTPUT)
def prepare_print(models: Annotated[list[str], Field(description="Absolute paths of the STL or 3MF files.")],
                  material: Annotated[str, Field(description='Material name, e.g. "PLA", "PETG".')] = "PLA",
                  goal: Annotated[Goal, Field(description="Print goal for the settings.")] = "balanced",
                  copies: Annotated[int, Field(description="Number of copies of each model, arranged on the plate.",
                                               ge=1)] = 1,
                  orientation: Annotated[Literal["auto", "as_is"], Field(
                      description='"auto": best orientation from analyze_model; "as_is": keep the file\'s.')] = "auto",
                  supports: Annotated[Literal["auto", "on", "off"], Field(
                      description='"auto": supports only when overhangs need them.')] = "auto",
                  bed_type: BedType = None,
                  filament: Annotated[str | None, Field(
                      description="Exact filament preset chosen by the user; overrides the material's default.")] = None,
                  extra_settings: Annotated[dict | None, Field(
                      description='Extra print settings, as Bambu strings: {"brim_type": "no_brim"}.')] = None,
                  ) -> dict:
    """Turn an STL (or geometry-only 3MF) into a print-ready Bambu project in one call: analysis,
    best orientation, material presets, build plate, supports and brim when needed, copies arranged,
    then slice. Returns time, weight, the decisions made, warnings and the result.3mf (under output/).
    Use it for raw models; for a complete Bambu project use optimize or slice_model instead."""
    return prepare.prepare(models, material, goal, copies, orientation, supports, bed_type,
                           filament, extra_settings)


@mcp.tool(title="Slice history", annotations=READ)
def slice_history(limit: Annotated[int, Field(description="Maximum number of slices to return.", ge=1)] = 20,
                  search: Annotated[str | None, Field(
                      description="Words from the model name or variant label to filter on.")] = None,
                  ) -> list[dict]:
    """List previous slices, newest first: models, presets, changed settings, time, weight, number
    of checks and the result.3mf path. Read-only. Use it to find an earlier result again instead of
    slicing anew."""
    return history.read(limit, search)


@mcp.tool(title="Printer status",
          annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                      open_world_hint=True))
def printer_status(include_raw: Annotated[bool, Field(
                       description="Also return the printer's raw MQTT report.")] = False) -> dict:
    """Read the printer's live status over the local network (MQTT): print job and progress,
    temperatures, fans, AMS trays and loaded filaments, HMS errors. Strictly read-only: it never
    sends commands. Needs the printer's host, serial and access code in config.json (see
    connector_info); fails if they are missing or the printer is off."""
    return printer.status(include_raw=include_raw)


@mcp.tool(title="Set up defaults", annotations=OUTPUT)
def setup_defaults(machine: Annotated[str | None, Field(
                       description='Exact machine preset, e.g. "Bambu Lab A1 0.4 nozzle"; its standard '
                                   "process follows.")] = None,
                   bed_type: Annotated[str | None, Field(
                       description='Usual build plate, e.g. "Textured PEI Plate".')] = None,
                   filament: Annotated[str | None, Field(
                       description='Usual filament: a preset or a material name such as "PLA Matte", adapted '
                                   "to the printer.")] = None,
                   ) -> dict:
    """Read or save the user's default printer, build plate and filament (stored in config.json).
    Without arguments: returns the current values and the available choices. With arguments:
    validates them and saves only those given. Call it on first use (connector_info.setup_needed)
    or when the user changes printer, plate or usual filament."""
    if not (machine or bed_type or filament):
        return {**defaults.current(), "options": defaults.options()}
    return defaults.configure(machine, bed_type, filament)


@mcp.tool(title="Connector info", annotations=READ)
def connector_info() -> dict:
    """Return the connector's status: whether first-use setup is needed, the saved defaults, the
    Bambu Studio and preset paths, the output folder, and whether the printer is configured.
    Read-only. Call it first in a session: if `setup_needed` is true, ask the user for their printer,
    build plate and filament, then call setup_defaults."""
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
