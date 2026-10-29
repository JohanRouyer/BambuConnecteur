# Connecteur Bambu Studio pour Claude

Serveur MCP local qui permet à Claude de lire et régler tes presets Bambu Studio, modifier tes
projets 3MF, slicer pour comparer des réglages et lire l'état de ta P1S en réseau local.

## Outils

| Outil | Rôle |
|---|---|
| `list_presets` | Liste les presets process / filament / machine (compatibles P1S par défaut) |
| `get_preset` | Réglages d'un preset, héritage résolu, filtrables par mot-clé |
| `compare_presets` | Différences entre deux presets |
| `save_preset` | Crée ou modifie un preset utilisateur (sauvegarde dans `backups/` avant d'écrire) |
| `inspect_3mf` | Résumé d'un 3MF : presets, objets, plateaux, résultats de slicing |
| `get_3mf_settings` | Réglages d'un projet 3MF |
| `edit_3mf` | Copie modifiée d'un 3MF (`<nom>_claude.3mf`), réglages globaux ou par objet |
| `slice_model` | Slice via `bambu-studio.exe` : temps, poids, avertissements, contrôles ; transforme aussi un STL ou un 3MF « géométrie seule » en projet Bambu complet |
| `compare_slices` | Slice plusieurs variantes en parallèle en un appel : tableau temps / poids / écart avec l'original |
| `optimize` | Recettes P1S (`qualite`, `equilibre`, `vitesse`, `solidite`, `leger`) comparées en parallèle, avec la variante conseillée |
| `check_settings` | Contrôle un 3MF sans slicer : débit volumétrique et vitesse réelle par type de ligne, refroidissement, pièges par matériau |
| `prepare_print` | STL / 3MF → projet P1S prêt en un appel : orientation, preset du matériau, plateau, supports, bordure, copies, slice |
| `analyze_model` | Géométrie d'un STL / 3MF : dimensions, volume, surplombs et ponts selon 6 orientations, meilleure orientation |
| `material_guide` | Conseils P1S par matériau : preset, plateaux et températures, capot / porte, AMS, buse, séchage |
| `slice_history` | Derniers slices : modèles, presets, réglages modifiés, temps, poids, fichier produit |
| `printer_status` | État de la P1S (températures, progression, AMS, erreurs HMS), en lecture seule |
| `connector_info` | Chemins utilisés et état de la config |

Les résultats de slicing vont dans `output/<projet>/<variante>/<horodatage>[_plateau-N]/` (variante :
`original`, `qualite`, `vitesse`... ou `slice` pour un slice simple). Un slice identique (mêmes modèles, réglages, presets et
version de Bambu Studio) est renvoyé depuis le cache `output/.cache/` ; supprimer ce dossier le vide.
Chaque slice est noté dans `output/history.jsonl`. Si Bambu Studio se fige (rare), le slice est
relancé une fois après 5 min, puis abandonné avec un message clair.

## Tests

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```
```bash
.venv\Scripts\python.exe -m pytest tests
```

Les tests unitaires (géométrie, contrôles, cache, historique) tournent en moins d'une seconde.
Les tests d'intégration slicent de vrais modèles avec Bambu Studio (environ 1 min) et sont ignorés
s'il n'est pas installé. Les modèles de test sont générés à la volée : aucun fichier à fournir.

## Imprimante (facultatif)

Copie `config.example.json` en `config.json` (s'il n'existe pas déjà ; il n'est pas suivi par git) et remplis la section `printer` :

- `host` : l'adresse IP de la P1S (écran de l'imprimante → Paramètres → Réseau)
- `serial` : le numéro de série (Paramètres → Appareil)
- `access_code` : le code d'accès LAN (Paramètres → Réseau)

Le code d'accès donne le contrôle local de l'imprimante : ce fichier doit rester sur ton PC.

## Remarques

- Redémarre Bambu Studio après une modification de preset pour qu'il la voie.
- L'analyse de surplombs est une estimation géométrique (plus de 60° par rapport à la verticale ;
  les faces horizontales comptent comme des ponts) : les avertissements du slicer font foi.
- `bambu_mcp/settings_keys.json` liste tous les réglages d'un projet Bambu Studio : il permet de
  modifier par preset des réglages restés à leur valeur par défaut (`brim_type`…).
- `edit_3mf` n'écrase jamais l'original, sauf si on lui donne le même chemin en sortie (une copie `.backup` est alors faite).
- Le connecteur ne lance jamais d'impression : tu ouvres le 3MF produit dans Bambu Studio et tu imprimes toi-même.

## Skill « impression-3d »

[skills/impression-3d/SKILL.md](skills/impression-3d/SKILL.md) fait utiliser le connecteur
automatiquement dès qu'on parle d'impression 3D ou qu'on donne un fichier STL / 3MF, et rendre un
résumé complet (pièce, matériau, temps, poids, variantes, recommandation, fichier prêt). Il est
installé dans `%USERPROFILE%\.claude\skills\impression-3d\`. Après une modification dans le dépôt,
recopier le fichier :

```bash
cp skills/impression-3d/SKILL.md ~/.claude/skills/impression-3d/SKILL.md
```

## Installation dans Claude Code

Déjà fait sur ce PC : le serveur `bambu-studio` est déclaré dans `%USERPROFILE%\.claude.json`
(section `mcpServers`). Si tu déplaces ce dossier, refais l'environnement Python puis mets à jour
les deux chemins de cette déclaration :

```bash
python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt
```
