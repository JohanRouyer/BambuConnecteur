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
| `printer_status` | État de la P1S (températures, progression, AMS, erreurs HMS), en lecture seule |
| `connector_info` | Chemins utilisés et état de la config |

Les résultats de slicing vont dans `output/`. Un slice identique (mêmes modèles, réglages, presets et
version de Bambu Studio) est renvoyé depuis le cache `output/.cache/` ; supprimer ce dossier le vide.

## Imprimante (facultatif)

Copie `config.example.json` en `config.json` (s'il n'existe pas déjà ; il n'est pas suivi par git) et remplis la section `printer` :

- `host` : l'adresse IP de la P1S (écran de l'imprimante → Paramètres → Réseau)
- `serial` : le numéro de série (Paramètres → Appareil)
- `access_code` : le code d'accès LAN (Paramètres → Réseau)

Le code d'accès donne le contrôle local de l'imprimante : ce fichier doit rester sur ton PC.

## Remarques

- Redémarre Bambu Studio après une modification de preset pour qu'il la voie.
- `edit_3mf` n'écrase jamais l'original, sauf si on lui donne le même chemin en sortie (une copie `.backup` est alors faite).
- Le connecteur ne lance jamais d'impression : tu ouvres le 3MF produit dans Bambu Studio et tu imprimes toi-même.

## Installation dans Claude Code

Déjà fait sur ce PC : le serveur `bambu-studio` est déclaré dans `%USERPROFILE%\.claude.json`
(section `mcpServers`). Si tu déplaces ce dossier, refais l'environnement Python puis mets à jour
les deux chemins de cette déclaration :

```bash
python -m venv .venv && .venv\Scripts\python.exe -m pip install -r requirements.txt
```
