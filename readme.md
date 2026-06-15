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
```
