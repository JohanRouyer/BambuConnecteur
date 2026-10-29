---
name: impression-3d
description: Analyse automatique d'un fichier 3D pour l'imprimante Bambu Lab de l'utilisateur (P1S, X1C, A1…) avec le connecteur bambu-studio, puis résumé complet (pièce, matériau, temps, poids, variantes, recommandation, fichier prêt). À utiliser dès que l'utilisateur parle d'impression 3D, d'imprimer, de slicer, de Bambu / P1S / A1 / X1, de filament, et dès qu'il donne ou mentionne un fichier .stl, .3mf (ou .step / .obj) — même sans demander explicitement d'analyse.
allowed-tools: AskUserQuestion, mcp__bambu-studio__connector_info, mcp__bambu-studio__setup_defaults, mcp__bambu-studio__inspect_3mf, mcp__bambu-studio__get_3mf_settings, mcp__bambu-studio__check_settings, mcp__bambu-studio__analyze_model, mcp__bambu-studio__material_guide, mcp__bambu-studio__slice_model, mcp__bambu-studio__compare_slices, mcp__bambu-studio__optimize, mcp__bambu-studio__prepare_print, mcp__bambu-studio__slice_history, mcp__bambu-studio__list_presets, mcp__bambu-studio__get_preset, mcp__bambu-studio__printer_status
---

# Impression 3D sur une Bambu Lab

L'utilisateur imprime sur l'imprimante enregistrée dans le connecteur (`connector_info` → `defaults`) :
modèle et buse, plateau habituel, filament habituel. Le connecteur MCP `bambu-studio` fait tout le
travail : ne pas deviner des temps ou des poids, toujours les obtenir en slicant. Dans le résumé, nomme
l'imprimante par son modèle (« ta P1S », « ton A1 mini »).

Réponds en français, tutoie l'utilisateur.

## Règles

- **Jamais** d'impression lancée, de preset enregistré (`save_preset`) ni de fichier d'origine modifié
  (`edit_3mf` sur l'original) sans accord explicite : tout ce que produit ce skill va dans `output/`.
- **Première utilisation** (`setup_needed` à true) : configurer d'abord les valeurs par défaut
  (étape 0), puis continuer la demande.
- **Une seule question à chaque impression, toujours posée avant de slicer : le filament** (voir étape 3). Ne choisis jamais
  le filament toi-même, même si le 3MF en contient un. Pour le reste (objectif, copies…), pas de
  question : choisis des valeurs par défaut raisonnables, dis lesquelles, et propose de relancer avec
  d'autres à la fin.
- Lance les appels indépendants en parallèle (par exemple `analyze_model`, `inspect_3mf` et
  `material_guide` dans le même message).

## Déroulé

0. **Configuration** : appelle `connector_info` (en même temps que l'étape 3 si c'est déjà réglé).
   - `setup_needed` à false : rien à demander, utilise `defaults`.
   - `setup_needed` à true, c'est la première utilisation : dis-le en une phrase, puis pose ces trois
     questions dans un seul `AskUserQuestion` :
     - **imprimante** : P1S, X1 Carbon, A1, A1 mini (l'utilisateur peut en nommer une autre) ;
     - **plateau habituel** : Textured PEI Plate, Cool Plate, High Temp Plate, Engineering Plate ;
     - **filament habituel** : Bambu PLA Basic, Bambu PLA Matte, Bambu PETG HF, ou un autre.
     Demande aussi la buse si elle n'est pas de 0,4 mm (rare : une seule phrase, sans question
     séparée). Enregistre avec `setup_defaults` : `machine` = « Bambu Lab <modèle> <buse> nozzle »
     (nom exact pris dans `setup_defaults` sans argument → `options.machines` en cas de doute),
     `bed_type`, `filament` (preset ou matériau, adapté à l'imprimante). Confirme en une ligne ce qui
     est enregistré, et que ça se change à tout moment en le demandant (« change mon imprimante »).
   - Si l'utilisateur demande de changer d'imprimante, de plateau ou de filament habituel, même hors
     d'une impression : `setup_defaults` avec la nouvelle valeur.

1. **Repérer les fichiers** : chemins donnés ou fichiers joints. `.step`, `.stp`, `.obj` ne sont pas
   lus par le connecteur : demande de les exporter en STL ou 3MF (Bambu Studio sait ouvrir un STEP
   et l'enregistrer en 3MF), puis arrête-toi.

2. **Déduire le contexte** du message de l'utilisateur :
   - objectif : `qualite`, `equilibre` (par défaut), `vitesse`, `solidite` (pièce mécanique, support,
     fixation), `leger` ;
   - nombre de copies (STL seulement).

3. **Analyser, puis demander le filament** :
   - en parallèle : `analyze_model` sur chaque fichier (dimensions, volume, tenue sur l'imprimante, surplombs,
     orientation) et `inspect_3mf` si c'est un 3MF (projet Bambu complet ou géométrie seule, et
     `filament_settings_id` du fichier) ;
   - puis demande le filament avec `AskUserQuestion`, sauf si l'utilisateur l'a déjà nommé dans ce
     message : propose le filament habituel (`defaults.filament`), puis celui du fichier s'il y en a un
     (« celui du fichier : PolyLite PLA ») et un filament adapté à la pièce (PETG HF pour une pièce exposée à la chaleur ou
     aux chocs, par exemple) ; l'utilisateur peut toujours répondre autre chose ;
   - `material_guide` pour le matériau choisi, avec `filament` quand une marque ou un preset précis est
     nommé ; si le nom ne correspond à aucun preset, cherche avec `list_presets` (`kind` filament,
     `search`) et retiens le plus proche, en le disant.

4. **Slicer** avec le preset filament choisi selon le cas :
   - **Projet Bambu avec réglages** (3MF qui a `has_project_settings` à true) : `check_settings`, puis
     `optimize` avec l'objectif retenu (`compare_all` à true) et `filaments` = [preset choisi], même
     quand c'est celui du fichier. Il slice l'original et les 5 recettes en parallèle et donne la
     variante conseillée. Le filament est remplacé, les réglages d'impression du projet sont gardés.
     Un projet fait pour une autre imprimante est converti pour celle de l'utilisateur
     automatiquement : signale-le dans le résumé.
   - **Projet à plusieurs plateaux** : un seul appel avec `plate` à 0 (la valeur par défaut), jamais un
     appel par plateau. Chaque variante donne un seul `result.3mf` avec tous les plateaux, et
     `plates` donne le détail par plateau.
   - L'encombrement total d'`analyze_model` sur un projet à plusieurs plateaux est celui de la scène
     entière : ne conclus pas « ne tient pas » tant que le slice réussit.
   - **STL ou 3MF géométrie seule** : `prepare_print` (matériau, `filament` = preset choisi, objectif,
     copies). Puis `optimize` sur le `project_3mf` produit, avec le même `filaments`, pour montrer les
     autres objectifs.
   - Si la pièce ne tient pas sur l'imprimante (`bed_mm` d'`analyze_model`), ne slice pas : explique et propose de réduire l'échelle,
     de la coucher ou de la découper.

5. **Imprimante** (facultatif) : `printer_status`. Si ça échoue parce que `config.json` n'est pas
   rempli ou que l'imprimante est éteinte, ignore-le sans le signaler comme une erreur ; sinon,
   mentionne l'état, le filament chargé dans l'AMS (correspond-il au matériau ?) et les erreurs HMS.

## Résumé à rendre

Le résumé est la réponse finale : complet mais lisible, avec des tableaux plutôt que des pavés.
Supprime une section quand elle n'apporte rien.

```markdown
## 🧩 La pièce
<nom> : L × l × H mm, <volume> cm³, <tient / ne tient pas> sur <l'imprimante>.
Orientation : <retenue et pourquoi> · Supports : <non / oui, pourquoi> · Bordure : <non / oui>

## 🧵 Matériau et préparation
| | |
|---|---|
| Filament | <preset> |
| Plateau | <plateau> à <°C> |
| Buse | <°C> (+ alerte acier trempé si abrasif) |
| Capot / porte | <conseil> |
| AMS | <oui / bobine externe> |

## ⏱️ Temps et poids
| Variante | Temps | Poids | Écart |
|---|---|---|---|
| ... (original ou préparation, puis les recettes) |

<plusieurs plateaux : une ligne de détail par plateau pour la variante conseillée>

## ✅ Recommandation
<variante conseillée, en une ou deux phrases : pourquoi elle, pour cet usage>

## ⚠️ Points d'attention
<contrôles et avertissements du slicer, traduits en conséquences concrètes ;
vitesses plafonnées par le débit du filament : dire que c'est le filament qui limite>

## 📁 Fichier prêt
`<chemin du result.3mf de la variante conseillée>` : à ouvrir dans Bambu Studio, vérifier
l'aperçu, puis imprimer.

**Pour aller plus loin** : <1 à 3 propositions : autre matériau, autre objectif, plus de copies,
enregistrer les réglages en preset>
```

Donne toujours les temps au format « 1 h 05 » et les poids en grammes à une décimale.
