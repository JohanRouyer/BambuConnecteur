"""Serveur MCP : donne à Claude l'accès aux presets, projets, slicer et imprimante Bambu."""
import functools
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis, config, geometry, history, materials, prepare, presets, printer, slicer, threemf

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
def compare_slices(models: list[str], variants: dict[str, dict], include_original: bool = True,
                   machine: str | None = None, process: str | None = None,
                   filaments: list[str] | None = None, plate: int = 0,
                   bed_type: str | None = None) -> dict:
    """Slice plusieurs variantes EN PARALLÈLE en un seul appel : {nom: {réglage: valeur}}.
    Renvoie temps, poids, écart en % avec l'original et contrôles de chaque variante.
    Sur un 3MF sans `machine`, les réglages s'appliquent au projet (l'original n'est pas modifié)."""
    return slicer.compare(models, variants, include_original, machine, process, filaments, plate, bed_type)


@mcp.tool()
def optimize(models: list[str], goal: Literal["qualite", "equilibre", "vitesse", "solidite", "leger"],
             machine: str | None = None, process: str | None = None,
             filaments: list[str] | None = None, plate: int = 0, bed_type: str | None = None,
             compare_all: bool = True) -> dict:
    """Recettes P1S prêtes à l'emploi : slice l'original et les 5 objectifs en parallèle,
    puis désigne la variante de `goal`. `compare_all` false : seulement l'original et `goal`."""
    return slicer.optimize(models, goal, machine, process, filaments, plate, bed_type, compare_all)


@mcp.tool()
def check_settings(path: str) -> dict:
    """Contrôle un projet 3MF sans slicer : débit volumétrique par type de ligne (vitesse réelle
    quand le débit max du filament plafonne), vitesses machine, refroidissement, pièges par matériau."""
    return analysis.check_3mf(path)


@mcp.tool()
def analyze_model(path: str) -> dict:
    """Géométrie d'un STL ou 3MF : dimensions, volume, tient-il sur la P1S, assise, surplombs
    et ponts pour 6 orientations, meilleure orientation et conseils (supports, bordure)."""
    return geometry.analyze(path)


@mcp.tool()
def material_guide(material: str | None = None, filament: str | None = None) -> dict:
    """Conseils P1S par matériau (PLA, PETG, ABS, ASA, PC, TPU, PA-CF, …) : preset filament,
    plateaux et températures, capot / porte, AMS, buse, séchage. Sans `material` : la liste."""
    return materials.guide(material, filament)


@mcp.tool()
def prepare_print(models: list[str], material: str = "PLA",
                  goal: Literal["qualite", "equilibre", "vitesse", "solidite", "leger"] = "equilibre",
                  copies: int = 1, orientation: Literal["auto", "as_is"] = "auto",
                  supports: Literal["auto", "on", "off"] = "auto", bed_type: str | None = None,
                  filament: str | None = None, extra_settings: dict | None = None) -> dict:
    """De STL / 3MF à projet P1S prêt à imprimer en un appel : analyse, meilleure orientation,
    presets du matériau, plateau, supports et bordure si nécessaires, copies disposées, slice.
    Renvoie temps, poids, décisions prises, avertissements et le result.3mf à ouvrir dans Bambu Studio."""
    return prepare.prepare(models, material, goal, copies, orientation, supports, bed_type,
                           filament, extra_settings)


@mcp.tool()
def slice_history(limit: int = 20, search: str | None = None) -> list[dict]:
    """Derniers slices (plus récents d'abord) : modèles, presets, réglages modifiés, temps, poids,
    nombre de contrôles et result.3mf. `search` : mots du nom de modèle ou du label."""
    return history.read(limit, search)


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
