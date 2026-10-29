# BambuConnecteur

**Connecteur MCP qui donne à Claude l'accès à Bambu Studio et à ton imprimante Bambu Lab.**

Donne un fichier STL ou 3MF à Claude : il analyse la pièce, te demande ton filament, slice plusieurs
variantes avec le vrai moteur de Bambu Studio, compare temps et poids, puis te rend un projet `.3mf`
prêt à ouvrir et imprimer. Tout tourne en local sur ton PC.

Fonctionne avec les imprimantes **Bambu Lab** (P1S, P1P, X1 Carbon, A1, A1 mini…) : à la première
utilisation, Claude te demande ton imprimante, ton plateau et ton filament habituels. Recettes
calibrées sur une P1S avec buse 0,4 mm.

---

## Sommaire

- [Ce que ça fait](#ce-que-ça-fait)
- [Exemple](#exemple)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Outils disponibles](#outils-disponibles)
- [Comment ça marche](#comment-ça-marche)
- [Sécurité](#sécurité)
- [Limites connues](#limites-connues)
- [Dépannage](#dépannage)
- [Développement](#développement)

---

## Ce que ça fait

- **Configuration à la première utilisation** : imprimante, plateau et filament habituels, demandés
  une fois puis enregistrés. Le volume d'impression, les presets et les accélérations suivent
  l'imprimante choisie.
- **Analyse de pièce** : dimensions, volume, tenue sur le plateau, surplombs et ponts selon
  6 orientations, meilleure orientation, besoin de supports ou de bordure.
- **Slicing réel** avec `bambu-studio.exe` : temps, poids, temps par type de ligne, avertissements.
- **Comparaison de recettes** en parallèle (`qualite`, `equilibre`, `vitesse`, `solidite`, `leger`),
  avec la variante conseillée et le détail par plateau.
- **Projets multi-plateaux** : un seul `result.3mf` contient tous les plateaux et leur G-code.
- **Conversion automatique** : un projet fait pour une autre imprimante est converti pour la tienne, avec les réglages d'impression de l'auteur gardés.
- **Changement de filament** : applique ton filament (températures, plateau, débit, refroidissement)
  à n'importe quel projet.
- **Contrôles** : débit volumétrique et vitesse réelle par type de ligne, couche trop épaisse,
  refroidissement, remplissage lightning, pièges par matériau.
- **Presets** : lire, comparer, créer ou modifier tes presets Bambu Studio (avec sauvegarde).
- **Imprimante** (facultatif) : état en réseau local, températures, AMS, erreurs HMS, en lecture seule.

Le connecteur **ne lance jamais d'impression** : tu ouvres le 3MF produit dans Bambu Studio et tu
imprimes toi-même.

## Exemple

> **Toi :** voilà ma coque de caméra, fais-la en PLA Matte noir Bambu
> `C:\Users\moi\Downloads\coque.3mf`
>
> **Claude :** analyse les 4 plateaux, convertit le projet (fait pour une X1C) pour ta P1S, applique
> le preset `Bambu PLA Matte`, slice les 6 variantes en parallèle, puis répond :
>
> | Variante | Temps | Poids |
> |---|---|---|
> | Original | 9 h 11 | 459,3 g |
> | **Équilibre** | **9 h 32** | **454,1 g** |
> | Vitesse | 7 h 29 | 379,4 g |
> | … | | |
>
> Recommandation, points d'attention, détail par plateau et chemin du `result.3mf` à ouvrir.

Ce résumé vient du skill [`impression-3d`](skills/impression-3d/SKILL.md), fourni avec le connecteur
(voir l'[étape 4](#4-installer-le-skill-impression-3d-conseillé)).

## Prérequis

| | |
|---|---|
| Système | **Windows 10 ou 11** |
| Bambu Studio | Installé (chemin par défaut : `C:\Program Files\Bambu Studio`), lancé au moins une fois |
| Python | **3.10 ou plus récent** ([python.org](https://www.python.org/downloads/)) |
| Claude | [Claude Code](https://claude.com/claude-code) (terminal, application de bureau ou IDE) ou Claude Desktop |
| Git | Pour cloner le dépôt (ou télécharger le ZIP depuis GitHub) |

## Installation

Les commandes suivantes sont à lancer dans **PowerShell**.

### 1. Récupérer le projet

```powershell
git clone https://github.com/JohanRouyer/BambuConnecteur.git
cd BambuConnecteur
```

Place le dossier où tu veux, mais **ne le déplace plus ensuite** : Claude le lance par son chemin
complet.

### 2. Créer l'environnement Python

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Déclarer le connecteur auprès de Claude

**Claude Code** : depuis le dossier du projet, déclare-le pour tous tes projets (`--scope user`) :

```powershell
claude mcp add --scope user bambu-studio -- "$PWD\.venv\Scripts\python.exe" "$PWD\run_server.py"
```

**Claude Desktop** : ouvre *Paramètres → Développeur → Modifier la configuration* et ajoute, en
remplaçant le chemin par celui de ton dossier (barres obliques inverses doublées) :

```json
{
  "mcpServers": {
    "bambu-studio": {
      "command": "C:\\chemin\\vers\\BambuConnecteur\\.venv\\Scripts\\python.exe",
      "args": ["C:\\chemin\\vers\\BambuConnecteur\\run_server.py"]
    }
  }
}
```

Redémarre ensuite Claude pour qu'il charge le connecteur.

### 4. Installer le skill `impression-3d` (conseillé)

Le skill dit à Claude comment enchaîner les outils dès que tu parles d'impression 3D ou donnes un
fichier STL / 3MF : analyse, question sur le filament, slicing, résumé complet. Sans lui, les outils
restent utilisables, mais il faut les demander un par un.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force skills\impression-3d "$env:USERPROFILE\.claude\skills\"
```

Le skill est utilisé par Claude Code. Pour le mettre à jour après un `git pull`, relance la commande
`Copy-Item`.

### 5. Première utilisation

Donne un fichier à Claude, ou demande-lui *« configure mon imprimante »*. Comme rien n'est encore
réglé, il te demande d'abord :

- ton **imprimante** (P1S, X1 Carbon, A1, A1 mini… et la buse si elle n'est pas de 0,4 mm) ;
- ton **plateau** habituel (Textured PEI, Cool Plate, High Temp, Engineering) ;
- ton **filament** habituel (Bambu PLA Basic, PLA Matte, PETG HF…).

Il enregistre ces choix dans `config.json`, puis continue ta demande. Pour en changer plus tard,
dis-le simplement : *« je suis passé sur une A1 »*, *« mon plateau habituel est le Cool Plate »*.

Pour vérifier l'installation, demande *« donne-moi les infos du connecteur bambu-studio »* : la
réponse doit contenir `"exists": true` pour Bambu Studio et le chemin de tes presets.

## Configuration

Les valeurs par défaut se règlent en parlant à Claude (voir [Première utilisation](#5-première-utilisation)) :
il les écrit dans `config.json`, qui n'est pas suivi par git. Tu peux aussi éditer ce fichier à la
main, en partant de l'exemple :

```powershell
Copy-Item config.example.json config.json
```

| Clé | Rôle | Par défaut |
|---|---|---|
| `default_machine` | Imprimante visée par tous les slices (nom exact du preset machine) | `Bambu Lab P1S 0.4 nozzle` |
| `default_process` | Process de départ pour un STL sans presets (réglé avec l'imprimante) | `0.20mm Standard @BBL X1C` |
| `default_bed_type` | Plateau utilisé au slicing | celui du projet |
| `default_filament` | Filament proposé en premier, et utilisé pour un STL sans filament précisé | PLA Basic |
| `output_dir` | Dossier des résultats | `output\` dans le projet |
| `bambu_studio_dir` | Dossier d'installation de Bambu Studio | `C:\Program Files\Bambu Studio` |
| `bambu_data_dir` | Dossier de données de Bambu Studio | `%APPDATA%\BambuStudio` |
| `user_id` | Compte Bambu dont lire les presets utilisateur | le premier compte trouvé |
| `printer` | Connexion à l'imprimante en réseau local (voir ci-dessous) | vide |

> Les presets P1S de Bambu réutilisent les process de la X1C : c'est pourquoi le process par défaut
> s'appelle `@BBL X1C`. Il est choisi automatiquement quand tu changes d'imprimante.

### Connexion à l'imprimante (facultatif)

Seul l'outil `printer_status` en a besoin. Dans `config.json`, remplis la section `printer` :

| Clé | Où la trouver sur l'écran de l'imprimante |
|---|---|
| `host` | Adresse IP : *Paramètres → Réseau* |
| `serial` | Numéro de série : *Paramètres → Appareil* |
| `access_code` | Code d'accès LAN : *Paramètres → Réseau* |

Le PC et l'imprimante doivent être sur le même réseau.

## Outils disponibles

| Outil | Rôle |
|---|---|
| `analyze_model` | Géométrie d'un STL / 3MF : dimensions, volume, surplombs et ponts selon 6 orientations, meilleure orientation |
| `inspect_3mf` | Résumé d'un 3MF : presets, objets et leurs réglages propres, plateaux, résultats de slicing |
| `material_guide` | Conseils par matériau : preset, plateaux et températures, capot / porte, AMS, buse, séchage |
| `prepare_print` | STL / 3MF → projet prêt en un appel : orientation, preset du matériau, plateau, supports, bordure, copies, slice |
| `optimize` | Les 5 recettes et l'original slicés en parallèle, avec la variante conseillée |
| `compare_slices` | Tes propres variantes `{nom: {réglage: valeur}}` slicées en parallèle |
| `slice_model` | Un slice, avec presets et réglages au choix |
| `check_settings` | Contrôle un 3MF sans slicer : débit, vitesses réelles, refroidissement, pièges |
| `get_3mf_settings` | Tous les réglages d'un projet 3MF, filtrables par mot-clé |
| `edit_3mf` | Copie modifiée d'un 3MF (`<nom>_claude.3mf`), réglages globaux ou par objet |
| `list_presets` | Presets process / filament / machine, compatibles avec ton imprimante par défaut |
| `get_preset` | Réglages d'un preset, héritage résolu |
| `compare_presets` | Différences entre deux presets |
| `save_preset` | Crée ou modifie un preset utilisateur (l'ancien est sauvegardé dans `backups\`) |
| `slice_history` | Derniers slices : modèles, presets, réglages, temps, poids, fichier produit |
| `printer_status` | État de l'imprimante : impression, températures, AMS, erreurs HMS (lecture seule) |
| `setup_defaults` | Imprimante, plateau et filament par défaut : lecture, choix possibles, enregistrement |
| `connector_info` | Chemins utilisés, état de la configuration, première utilisation à faire ou non |

## Comment ça marche

### Les recettes

Elles s'appliquent **par-dessus** les réglages du projet. Sur un projet Bambu, tout le reste
(supports, bordures, réglages par objet de l'auteur) est conservé.

| Recette | Couche | Parois | Remplissage | Dessus / dessous | Accélérations |
|---|---|---|---|---|---|
| `qualite` | 0,16 mm | du projet | du projet | du projet | douces : mur 3 000, dessus 1 500 |
| `equilibre` | 0,20 mm | du projet | du projet | du projet | standard : 10 000, mur 5 000, dessus 2 000 |
| `vitesse` | 0,28 mm | 2 | adaptive cubic 12 % | 4 / 3 | franches : 14 000, mur 7 000 |
| `solidite` | 0,20 mm | 4 | gyroïde 25 % | 5 / 4 | du projet |
| `leger` | 0,24 mm | 2 | adaptive cubic 10 % | 4 / 3 | 12 000, mur 6 000 |

Quelques choix assumés :

- **Pas de remplissage lightning** : il laisse les couches du dessus en pont sur de grands vides.
  L'adaptive cubic garde l'essentiel du gain de poids sans ce défaut.
- **Peu de jeu sur les vitesses** : en PLA, le débit max du filament (15 à 22 mm³/s) plafonne déjà
  les vitesses. Les recettes jouent donc sur les accélérations, ramenées au besoin à 75 % du maximum
  de ton imprimante (9 000 mm/s² sur une A1, qui plafonne à 12 000).

### Le filament

Avec le skill, Claude te demande toujours ton filament avant de slicer, même si le fichier en
contient un, en proposant d'abord ton filament habituel. Les presets suivent ton imprimante
(`Bambu PLA Basic @BBL A1` sur une A1, par exemple). Sur un projet 3MF, le preset choisi remplace le filament du projet sur tous ses
emplacements, et les réglages d'impression de l'auteur restent.

### L'imprimante

Tous les slices visent ton imprimante par défaut. Un projet fait pour un autre modèle est converti
avant le slice : seule la partie imprimante change (G-code de départ et de fin, modèle, buse). Un STL
sans presets reçoit ton imprimante, son process standard et ton filament habituel. L'analyse de pièce
utilise le volume d'impression de ton imprimante (180 × 180 × 180 mm pour une A1 mini, par exemple).

### Les fichiers produits

```text
output/
├── <projet>/
│   ├── original/<date-heure>/result.3mf
│   ├── equilibre/<date-heure>/result.3mf
│   └── …
├── .cache/          slices déjà faits (supprimer le dossier pour le vider)
└── history.jsonl    une ligne par slice
```

- **Un seul `result.3mf` par variante**, avec tous les plateaux et leur G-code.
- **Cache** : un slice identique (mêmes modèles, réglages, presets et version de Bambu Studio) est
  rendu instantanément.
- **Parallélisme** : un Bambu Studio par paire de cœurs (6 sur un processeur à 12 cœurs).
- **Relance** : si Bambu Studio se fige (rare), le slice est relancé une fois, puis abandonné avec un
  message clair.

## Sécurité

- Aucune impression n'est lancée : `printer_status` est en lecture seule.
- Les fichiers d'origine ne sont jamais modifiés : les résultats vont dans `output\`, et `edit_3mf`
  écrit une copie (sauf si on lui donne le même chemin en sortie ; une copie `.backup` est alors faite).
- `save_preset` sauvegarde l'ancien preset dans `backups\` avant d'écrire. Redémarre Bambu Studio
  pour qu'il voie un preset modifié.
- Le code d'accès de l'imprimante donne son contrôle en local : `config.json` doit rester sur ton PC
  (il est exclu de git).

## Limites connues

- **Windows uniquement** pour l'instant (chemins Windows, `taskkill`, `tasklist`).
- Recettes et conseils matériaux calibrés sur une **P1S avec buse 0,4 mm** : ils restent valables sur
  les autres Bambu, mais n'y ont pas été affinés.
- Les fichiers `.step` et `.obj` ne sont pas lus : ouvre-les dans Bambu Studio et enregistre-les en 3MF.
- L'analyse des surplombs est une estimation géométrique : les avertissements du slicer font foi.
- La couleur du filament n'est pas réglée : associe l'emplacement AMS à l'ouverture dans Bambu Studio.

## Dépannage

| Problème | Solution |
|---|---|
| `Bambu Studio introuvable` | Installe Bambu Studio, ou indique son dossier dans `bambu_studio_dir` |
| Les outils n'apparaissent pas dans Claude | Vérifie les deux chemins de la déclaration (étape 3), puis redémarre Claude |
| `Preset … introuvable` | Lance Bambu Studio une fois, connecte-toi à ton compte, puis réessaie (les noms proches sont proposés) |
| Le slice reste bloqué | Ferme les `bambu-studio.exe` restés ouverts dans le Gestionnaire des tâches |
| `printer_status` échoue | Vérifie l'IP, le code d'accès, le mode LAN et que le PC est sur le même réseau |
| Un changement du code n'est pas pris en compte | Redémarre Claude : le serveur est chargé au démarrage |

## Développement

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe -m pyflakes bambu_mcp tests
```

Les tests unitaires (géométrie, contrôles, cache, historique) prennent moins d'une seconde. Les tests
d'intégration slicent de vrais modèles avec Bambu Studio (environ 20 s) et sont ignorés s'il n'est
pas installé. Les modèles de test sont générés à la volée : aucun fichier à fournir.

```text
bambu_mcp/
├── server.py      outils MCP exposés à Claude
├── slicer.py      appel de la CLI Bambu Studio, recettes, comparaisons, cache
├── prepare.py     préparation complète d'un STL / 3MF
├── threemf.py     lecture et modification des projets 3MF
├── presets.py     presets système et utilisateur, héritage, écriture
├── geometry.py    analyse géométrique et orientation
├── analysis.py    contrôles des réglages
├── defaults.py    imprimante, plateau et filament par défaut
├── materials.py   conseils par matériau
├── printer.py     état de l'imprimante (MQTT, lecture seule)
├── history.py     historique des slices
└── config.py      chemins et config.json
skills/impression-3d/SKILL.md   skill Claude Code
```
