"""Serveur MCP : donne à Claude l'accès aux presets, projets, slicer et imprimante Bambu."""
import functools
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import config, presets, printer, slicer, threemf

Kind = Literal["process", "filament", "machine"]
EXPECTED_ERRORS = (KeyError, ValueError, OSError, TimeoutError, RecursionError)


def readable_errors(fn):
    """Remonte le message d'erreur tel quel (sinon le SDK le remplace par un message générique)."""
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
        "Accès local à Bambu Studio (P1S). Les valeurs de réglage sont des chaînes Bambu "
        "(\"0.2\", \"15%\", \"1\"/\"0\") ; une valeur simple est recopiée sur toutes les variantes. "
        "Méthode conseillée : lire le preset ou le projet, proposer les changements, slicer pour "
        "comparer temps et poids, puis seulement enregistrer. Bambu Studio doit être redémarré "
        "pour voir un preset modifié. L'outil imprimante est en lecture seule."
    ),
)


@mcp.tool()
def list_presets(kind: Kind, source: Literal["all", "user", "system"] = "user",
                 printer_name: str | None = "Bambu Lab P1S 0.4 nozzle",
                 search: str | None = None) -> list[dict]:
    """Liste les presets (process, filament ou machine). `printer_name` filtre ceux compatibles ;
    passer null pour tout voir. `search` : mots à trouver dans le nom."""
    return presets.list_presets(kind, source, printer_name, search)


@mcp.tool()
def get_preset(kind: Kind, name: str, key_filter: str | None = None,
               only_overrides: bool = False) -> dict:
    """Réglages d'un preset, héritage résolu. `key_filter` : mots-clés de nom de réglage
    (ex. "speed accel"). `only_overrides` : seulement ce que ce preset change par rapport à son parent."""
    source, path, data = presets.find(kind, name)
    values = presets.overrides(kind, name) if only_overrides else presets.resolve(kind, name)
    if key_filter:
        words = key_filter.lower().split()
        values = {k: v for k, v in values.items() if any(w in k.lower() for w in words)}
    return {"name": name, "source": source, "inherits": data.get("inherits"), "file": str(path),
            "count": len(values), "settings": values}


@mcp.tool()
def compare_presets(kind: Kind, preset_a: str, preset_b: str) -> list[dict]:
    """Réglages qui diffèrent entre deux presets du même type."""
    return presets.diff(kind, preset_a, preset_b)


@mcp.tool()
def save_preset(kind: Kind, name: str, settings: dict, parent: str | None = None) -> dict:
    """Crée (avec `parent`) ou met à jour un preset utilisateur. L'ancien fichier est sauvegardé
    dans backups/. À n'utiliser qu'après accord de l'utilisateur sur les changements."""
    return presets.save_user_preset(kind, name, settings, parent)


@mcp.tool()
def inspect_3mf(path: str) -> dict:
    """Résumé d'un fichier 3MF : origine, presets utilisés, objets et leurs réglages propres,
    plateaux, et résultats de slicing s'il en contient."""
    return threemf.inspect(path)


@mcp.tool()
def get_3mf_settings(path: str, key_filter: str | None = None) -> dict:
    """Tous les réglages d'un projet 3MF Bambu (ou ceux dont le nom contient un des mots de `key_filter`)."""
    return threemf.get_settings(path, key_filter)


@mcp.tool()
def edit_3mf(path: str, settings: dict | None = None, object_settings: dict | None = None,
             output_path: str | None = None) -> dict:
    """Écrit une copie modifiée d'un projet 3MF (par défaut <nom>_claude.3mf à côté de l'original).
    `settings` : réglages du projet. `object_settings` : {nom ou id d'objet: {réglage: valeur}}."""
    return threemf.edit(path, settings, object_settings, output_path)


@mcp.tool()
def slice_model(models: list[str], machine: str | None = None, process: str | None = None,
                filaments: list[str] | None = None, process_overrides: dict | None = None,
                filament_overrides: dict | None = None, plate: int = 0,
                bed_type: str | None = None, orient: bool = False, arrange: bool = False) -> dict:
    """Slice avec Bambu Studio et renvoie temps, poids, temps par type de ligne et avertissements.
    Sans presets, un 3MF Bambu garde ses propres réglages, et les overrides s'y appliquent
    (l'original n'est pas modifié). Avec `machine` (+ process, filaments),
    un STL ou un 3MF « géométrie seule » devient un projet Bambu complet (result.3mf).
    `plate` 0 = tous les plateaux. `bed_type` ex. "Textured PEI Plate"."""
    return slicer.run(models, machine, process, filaments, process_overrides, filament_overrides,
                      plate, bed_type, orient, arrange)


@mcp.tool()
def printer_status(include_raw: bool = False) -> dict:
    """État de la P1S en réseau local : impression, températures, ventilateurs, AMS, erreurs HMS."""
    return printer.status(include_raw=include_raw)


@mcp.tool()
def connector_info() -> dict:
    """Chemins utilisés par le connecteur et état de la configuration."""
    p = config.printer()
    return {"bambu_studio": str(config.executable()), "exists": config.executable().exists(),
            "user_presets": str(config.user_presets_dir()), "output_dir": str(config.output_dir()),
            "config_file": str(config.CONFIG_FILE),
            "printer_configured": all(p.get(k) for k in ("host", "serial", "access_code")),
            "bambu_studio_running": config.bambu_studio_running()}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
