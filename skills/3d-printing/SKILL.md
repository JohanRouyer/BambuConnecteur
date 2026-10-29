---
name: 3d-printing
description: Automatic analysis of a 3D file for the user's Bambu Lab printer (P1S, X1C, A1…) with the bambu-studio connector, then a full summary (part, material, time, weight, variants, recommendation, ready file). Use it as soon as the user talks about 3D printing, printing, slicing, Bambu / P1S / A1 / X1, filament, or gives or mentions an .stl, .3mf (or .step / .obj) file — even without explicitly asking for an analysis.
allowed-tools: AskUserQuestion, mcp__bambu-studio__connector_info, mcp__bambu-studio__setup_defaults, mcp__bambu-studio__inspect_3mf, mcp__bambu-studio__get_3mf_settings, mcp__bambu-studio__check_settings, mcp__bambu-studio__analyze_model, mcp__bambu-studio__material_guide, mcp__bambu-studio__slice_model, mcp__bambu-studio__compare_slices, mcp__bambu-studio__optimize, mcp__bambu-studio__prepare_print, mcp__bambu-studio__slice_history, mcp__bambu-studio__list_presets, mcp__bambu-studio__get_preset, mcp__bambu-studio__printer_status
---

# 3D printing on a Bambu Lab printer

The user prints on the printer saved in the connector (`connector_info` → `defaults`): model and
nozzle, usual build plate, usual filament. The `bambu-studio` MCP connector does all the work: never
guess times or weights, always get them by slicing. In the summary, call the printer by its model
("your P1S", "your A1 mini").

Answer in the user's language (in French, use « tu »).

## Rules

- **Never** start a print, save a preset (`save_preset`) or modify an original file (`edit_3mf` on the
  original) without explicit agreement: everything this skill produces goes to `output/`.
- **First use** (`setup_needed` is true): set the defaults first (step 0), then carry on with the request.
- **A single question for each print, always asked before slicing: the filament** (see step 3). Never
  pick the filament yourself, even if the 3MF has one. For everything else (goal, copies…), no
  question: pick sensible defaults, say which, and offer to run again with others at the end.
- Run independent calls in parallel (for example `analyze_model`, `inspect_3mf` and `material_guide`
  in the same message).

## Steps

0. **Setup**: call `connector_info` (together with step 3 if it is already set up).
   - `setup_needed` is false: nothing to ask, use `defaults`.
   - `setup_needed` is true, this is the first use: say so in one sentence, then ask these three
     questions in a single `AskUserQuestion`:
     - **printer**: P1S, X1 Carbon, A1, A1 mini (the user can name another one);
     - **usual build plate**: Textured PEI Plate, Cool Plate, High Temp Plate, Engineering Plate;
     - **usual filament**: Bambu PLA Basic, Bambu PLA Matte, Bambu PETG HF, or another one.
     Also ask about the nozzle if it is not 0.4 mm (rare: one sentence, not a separate question).
     Save with `setup_defaults`: `machine` = "Bambu Lab <model> <nozzle> nozzle" (exact name from
     `setup_defaults` without arguments → `options.machines` when in doubt), `bed_type`, `filament`
     (preset or material, adapted to the printer). Confirm in one line what was saved, and that it can
     be changed at any time by asking ("change my printer").
   - If the user asks to change their printer, build plate or usual filament, even outside a print:
     `setup_defaults` with the new value.

1. **Find the files**: given paths or attached files. `.step`, `.stp` and `.obj` files are not read by
   the connector: ask for an STL or 3MF export (Bambu Studio can open a STEP file and save it as 3MF),
   then stop.

2. **Infer the context** from the user's message:
   - goal: `quality`, `balanced` (default), `speed`, `strength` (mechanical part, bracket, mount),
     `light`;
   - number of copies (STL only).

3. **Analyze, then ask for the filament**:
   - in parallel: `analyze_model` on each file (dimensions, volume, fit on the printer, overhangs,
     orientation) and `inspect_3mf` if it is a 3MF (complete Bambu project or geometry only, and the
     file's `filament_settings_id`);
   - then ask for the filament with `AskUserQuestion`, unless the user already named it in this
     message: offer the usual filament (`defaults.filament`) first, then the file's filament if it has
     one ("the file's one: PolyLite PLA") and a filament suited to the part (PETG HF for a part exposed
     to heat or impacts, for example); the user can always answer something else;
   - `material_guide` for the chosen material, with `filament` when a brand or exact preset is named;
     if the name matches no preset, search with `list_presets` (`kind` filament, `search`) and keep the
     closest one, saying so.

4. **Slice** with the chosen filament preset, depending on the case:
   - **Bambu project with settings** (3MF with `has_project_settings` true): `check_settings`, then
     `optimize` with the chosen goal (`compare_all` true) and `filaments` = [chosen preset], even when
     it is the file's own. It slices the original and the 5 recipes in parallel and picks the
     recommended variant. The filament is replaced, the project's print settings are kept. A project
     made for another printer is converted to the user's automatically: mention it in the summary.
   - **Multi-plate project**: a single call with `plate` 0 (the default), never one call per plate.
     Each variant gives a single `result.3mf` with every plate, and `plates` gives the per-plate details.
   - On a multi-plate project, the overall size from `analyze_model` is the whole scene's: do not
     conclude "does not fit" as long as the slice succeeds.
   - **STL or geometry-only 3MF**: `prepare_print` (material, `filament` = chosen preset, goal, copies).
     Then `optimize` on the `project_3mf` it produced, with the same `filaments`, to show the other goals.
   - If the part does not fit the printer (`bed_mm` from `analyze_model`), do not slice: explain and
     suggest scaling it down, laying it down or splitting it.

5. **Printer** (optional): `printer_status`. If it fails because `config.json` is not filled in or the
   printer is off, skip it without reporting an error; otherwise mention its state, the filament loaded
   in the AMS (does it match the material?) and HMS errors.

## Summary to give

The summary is the final answer: complete but easy to read, with tables rather than walls of text.
Drop a section when it adds nothing. Translate the headings into the user's language.

```markdown
## 🧩 The part
<name>: L × W × H mm, <volume> cm³, <fits / does not fit> on <the printer>.
Orientation: <chosen and why> · Supports: <no / yes, why> · Brim: <no / yes>

## 🧵 Material and setup
| | |
|---|---|
| Filament | <preset> |
| Build plate | <plate> at <°C> |
| Nozzle | <°C> (+ hardened steel warning if abrasive) |
| Lid / door | <advice> |
| AMS | <yes / external spool> |

## ⏱️ Time and weight
| Variant | Time | Weight | Difference |
|---|---|---|---|
| ... (original or preparation, then the recipes) |

<several plates: one detail line per plate for the recommended variant>

## ✅ Recommendation
<recommended variant, in one or two sentences: why this one, for this use>

## ⚠️ Things to watch
<checks and slicer warnings, turned into concrete consequences;
speeds capped by the filament's max flow: say that the filament is the limit>

## 📁 Ready file
`<path of the recommended variant's result.3mf>`: open it in Bambu Studio, check the preview,
then print.

**Going further**: <1 to 3 suggestions: another material, another goal, more copies,
save the settings as a preset>
```

Always give times as "1 h 05" and weights in grams with one decimal.
