# CD78 (71_CD7892) — data processing

Python scripts for inspecting and processing the CD78 road database
(`cd78_v2026`, PostgreSQL + PostGIS).

## Setup

```bash
pip install -r requirements.txt
```

All scripts read the database connection (and schema names) from
`config/config.yaml` under the `source:` block. See `config/example_config.yaml`
for a template.

## Scripts

| Script | Purpose | Docs |
|---|---|---|
| `scripts/00_inspect_db.py` | Read-only introspection of the `client` / `public` / `rendu` schemas → `db_structure.md` + editable `db_descriptions.yaml`. | [00_inspect_db.md](scripts/00_inspect_db.md) |
| `scripts/01_copy_source_tables.py` | Copy raw tables from the original schema to the processing schema, promote `id` to PK, compute geometry calibration. | [01_copy_source_tables.md](scripts/01_copy_source_tables.md) |
| `scripts/02_analyse_overlapping.py` | Find overlapping segment pairs (geometry and cumulated-distance) in a source layer → CSV + Markdown report. | [02_analyse_overlapping.md](scripts/02_analyse_overlapping.md) |
| `scripts/03_take_most_recent_segment.py` | De-overlap a layer keeping the most recent segment → `<table>_most_recent` table with an `is_overlapping` flag. | [03_take_most_recent_segment.md](scripts/03_take_most_recent_segment.md) |
| `scripts/04_make_finest_overlay.py` | Finest linear-referencing overlay of ≥2 layers → one row per `(axe, cumuld, cumulf, value₁, value₂, …)` composition. | [04_make_finest_overlay.md](scripts/04_make_finest_overlay.md) |
| `scripts/05_build_troncon.py` | Decompose the overlay into individual M-calibrated `LineStringM` troncons → `client.troncon_client` (`id_tronc` PK, SRID 2154). | [05_build_troncon.md](scripts/05_build_troncon.md) |
| `scripts/11_map_matching.py` | Map-match `public.image` points onto `client.troncon_client` → sets `id_tronc`, `axe`, `cumuld`, projection geometry. | [11_map_matching.md](scripts/11_map_matching.md) |
| `scripts/12_update_notes.py` | Populate 26 `Note_*` degradation columns on `public.image` from `image_grade`, then compute `Note_Structure` / `Note_Surface`. | [12_update_notes.md](scripts/12_update_notes.md) |
| `scripts/13_generate_pas.py` | Generate fixed-step (50 m / 100 m) segments on the itinerary roads → `client.pas_50` / `client.pas_100` (line + per-step width, notes, surface). | [13_generate_pas.md](scripts/13_generate_pas.md) |
| `scripts/14_plan_travaux.py` | Apply the decision matrix (`matrice_decision_rules.md`) to `pas_50` / `pas_100`: états, traffic class, type, `Priorite`, `Technique_entretien`, `Cout_surfacique`, `Cout_Total`. | [14_plan_travaux.md](scripts/14_plan_travaux.md) |
| `scripts/31_export_rendu.py` | Export rendu layers to GeoJSON (4326), an Excel workbook (`pas_50`/`pas_100`, no geom), and a Leaflet + Chart.js `index.html` dashboard (logo, KPIs, cross-filters, charts on `pas_100`). | [31_export_rendu.md](scripts/31_export_rendu.md) |

## Key files

- `config/config.yaml` — DB connection + schema names (not committed; see example).
- `db_structure.md` — generated DB structure report.
- `db_descriptions.yaml` — hand-written table/column descriptions (preserved on re-run).
- `overlapping_definition.md` — definitions of geometry / cumul overlap.
- `task.md`, `task/todo.md` — current task description and working plan.

## Common usage

```bash
# Inspect the DB and (re)generate db_structure.md
python scripts/00_inspect_db.py

# Analyse overlapping segments in a layer
python scripts/02_analyse_overlapping.py --source client.20250916_trafic

# Keep the most-recent, non-overlapping segments
python scripts/03_take_most_recent_segment.py --source client.20250916_trafic --date-col annee

# Finest overlay of traffic × road-surface layers
python scripts/04_make_finest_overlay.py \
    --table 'client.20250916_trafic_most_recent:nb_pl' \
    --table 'client.20260227_couche_roulement:nature_cr'

# Decompose the overlay into M-calibrated troncons (client.troncon_client)
python scripts/05_build_troncon.py

# Enrich pas_50 / pas_100 with the maintenance decision matrix (priority, cost)
python scripts/14_plan_travaux.py

# Export rendu layers (GeoJSON + Excel + Leaflet viewer) to D:\Tmp\cd78_exports
python scripts/31_export_rendu.py
```
