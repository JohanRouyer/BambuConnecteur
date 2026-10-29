---
name: impression-3d
description: Analyse automatique d'un fichier 3D pour la Bambu Lab P1S avec le connecteur bambu-studio, puis résumé complet (pièce, matériau, temps, poids, variantes, recommandation, fichier prêt). À utiliser dès que l'utilisateur parle d'impression 3D, d'imprimer, de slicer, de Bambu / P1S, de filament, et dès qu'il donne ou mentionne un fichier .stl, .3mf (ou .step / .obj) — même sans demander explicitement d'analyse.
allowed-tools: mcp__bambu-studio__connector_info, mcp__bambu-studio__inspect_3mf, mcp__bambu-studio__get_3mf_settings, mcp__bambu-studio__check_settings, mcp__bambu-studio__analyze_model, mcp__bambu-studio__material_guide, mcp__bambu-studio__slice_model, mcp__bambu-studio__compare_slices, mcp__bambu-studio__optimize, mcp__bambu-studio__prepare_print, mcp__bambu-studio__slice_history, mcp__bambu-studio__list_presets, mcp__bambu-studio__get_preset, mcp__bambu-studio__printer_status
---

# Impression 3D sur la P1S

L'utilisateur imprime sur une **Bambu Lab P1S** (buse inox 0,4 mm d'origine, caisson fermé non chauffé,
plateau 256 × 256 mm, hauteur 250 mm). Le connecteur MCP `bambu-studio` fait tout le travail : ne pas
deviner des temps ou des poids, toujours les obtenir en slicant.

Réponds en français, tutoie l'utilisateur.

## Règles

- **Jamais** d'impression lancée, de preset enregistré (`save_preset`) ni de fichier d'origine modifié
  (`edit_3mf` sur l'original) sans accord explicite : tout ce que produit ce skill va dans `output/`.
- Ne pose pas de question avant d'analyser : choisis des valeurs par défaut raisonnables, dis lesquelles,
  et propose de relancer avec d'autres à la fin.
- Lance les appels indépendants en parallèle (par exemple `analyze_model`, `inspect_3mf` et
  `material_guide` dans le même message).

## Déroulé

1. **Repérer les fichiers** : chemins donnés ou fichiers joints. `.step`, `.stp`, `.obj` ne sont pas
   lus par le connecteur : demande de les exporter en STL ou 3MF (Bambu Studio sait ouvrir un STEP
   et l'enregistrer en 3MF), puis arrête-toi.

2. **Déduire le contexte** du message de l'utilisateur :
   - matériau (PLA par défaut ; sinon celui du projet 3MF, lu par `inspect_3mf` → `filament_type`) ;
   - objectif : `qualite`, `equilibre` (par défaut), `vitesse`, `solidite` (pièce mécanique, support,
     fixation), `leger` ;
   - nombre de copies (STL seulement).

3. **Analyser** (en parallèle) :
   - `analyze_model` sur chaque fichier : dimensions, volume, tenue sur la P1S, surplombs, orientation ;
   - `inspect_3mf` si c'est un 3MF : projet Bambu complet (réglages présents) ou géométrie seule ;
   - `material_guide` pour le matériau retenu.

4. **Slicer** selon le cas :
   - **Projet Bambu avec réglages** (3MF qui a `has_project_settings` à true) : `check_settings`, puis
     `optimize` avec l'objectif retenu (`compare_all` à true). Il slice l'original et les 5 recettes
     en parallèle et donne la variante conseillée. Un projet fait pour une autre imprimante (X1C, A1…)
     est converti en P1S automatiquement : signale-le dans le résumé.
   - **Projet à plusieurs plateaux** : un seul appel avec `plate` à 0 (la valeur par défaut), jamais un
     appel par plateau. Chaque variante donne un seul `result.3mf` avec tous les plateaux, et
     `plates` donne le détail par plateau.
   - L'encombrement total d'`analyze_model` sur un projet à plusieurs plateaux est celui de la scène
     entière : ne conclus pas « ne tient pas » tant que le slice réussit.
   - **STL ou 3MF géométrie seule** : `prepare_print` (matériau, objectif, copies). Puis `optimize`
     sur le `project_3mf` produit pour montrer les autres objectifs.
   - Si la pièce ne tient pas sur la P1S, ne slice pas : explique et propose de réduire l'échelle,
     de la coucher ou de la découper.

5. **Imprimante** (facultatif) : `printer_status`. Si ça échoue parce que `config.json` n'est pas
   rempli ou que l'imprimante est éteinte, ignore-le sans le signaler comme une erreur ; sinon,
   mentionne l'état, le filament chargé dans l'AMS (correspond-il au matériau ?) et les erreurs HMS.

## Résumé à rendre

Le résumé est la réponse finale : complet mais lisible, avec des tableaux plutôt que des pavés.
Supprime une section quand elle n'apporte rien.

```markdown
## 🧩 La pièce
<nom> : L × l × H mm, <volume> cm³, <tient / ne tient pas> sur la P1S.
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
