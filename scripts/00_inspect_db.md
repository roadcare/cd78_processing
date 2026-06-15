# `00_inspect_db.py`

Read-only DB introspection. Connects to the PostgreSQL database described in
`config/config.yaml`, inspects three schemas — **client**, **processing**,
and **reporting** — and produces:

- **`db_structure.md`** — a human-readable Markdown report (tables, columns,
  PKs, FKs, indexes, row estimates, sizes), regenerated from scratch on
  every run.
- **`db_descriptions.yaml`** — a sidecar YAML file holding hand-written
  table / column / database descriptions. **Persisted across re-runs** —
  new tables and columns appear as empty entries; entries for objects no
  longer in the DB are moved under `_orphans` so notes are never silently
  deleted.

---

## What it does

1. Reads connection params from `config/config.yaml` (the `source` block).
2. Identifies the three schemas to inspect by name from config:
   `client_schema`, `processing_schema`, `reporting_schema`.
3. For each schema:
   - Lists base tables only (skips views and any table owned by a PostgreSQL
     extension — e.g. PostGIS's `spatial_ref_sys`).
   - For each table, queries `pg_catalog` for columns, primary key,
     foreign keys, indexes, row estimate, total size.
4. Loads existing `db_descriptions.yaml` if present, merges with the
   freshly-introspected structure (preserves your text), and writes it
   back.
5. Renders the Markdown report into `db_structure.md`.

If a schema listed in `config.yaml` doesn't exist in the database, the
report says so explicitly and the run continues — no crash.

---

## Config keys used

Under `source:` in `config/config.yaml`:

| Key | Purpose |
|---|---|
| `host`, `port`, `user`, `password`, `database` | Connection params |
| `client_schema`            | First schema to inspect (e.g. `client`)     |
| `processing_schema`        | Second schema to inspect (e.g. `public`)    |
| `reporting_schema`         | Third schema to inspect (e.g. `rendu`)      |

The script does **not** read `original_schema` — by design it leaves
`fromrcweb` (the upstream raw schema) out of the report.

---

## Filters applied

- **Views are skipped entirely** — only base tables (`relkind IN ('r','p')`)
  appear in the report.
- **Extension-owned tables are skipped** via `pg_depend.deptype = 'e'`. So
  PostGIS's `spatial_ref_sys` (and any future extension tables) doesn't
  appear in the report.

---

## The descriptions sidecar

`db_descriptions.yaml` has this shape:

```yaml
_database:
  description: |
    Free-text description of the database and its use case.
    Renders as the "## About this database" section at the top of the
    Markdown report.

client:
  itineraire_test:
    description: ""
    columns:
      id: ""
      geom: ""

public:
  session:
    description: ""
    columns:
      id: ""

_orphans:
  # tables/columns that existed in a previous run but no longer in the DB
```

Editing rules:
- Top-level keys named after the **schemas** (e.g. `client`, `public`,
  `rendu`).
- Two reserved top-level keys:
  - `_database` — global description (rendered near the top of
    `db_structure.md`).
  - `_orphans` — script-managed; entries no longer in the DB end up here.
- Per-table `description` is a string (use YAML's `|` block scalar for
  multi-line).
- Per-column `description` is a string.

What re-running the script does to the YAML:
- New tables / columns added with empty `description`.
- Existing descriptions left **completely untouched**.
- Tables / columns no longer in the DB moved under `_orphans`.
- The reserved `_database` block is preserved as-is.

What the YAML drives in the report:
- `_database.description` → "## About this database" section.
- `<schema>.<table>.description` → `**Description:**` line under each
  table's heading, and the right-most column in each schema's table
  overview.
- `<schema>.<table>.columns.<col>` → right-most "Description" column in
  the per-table column listing.

---

## Usage

```bash
# Default run — uses config/config.yaml, writes db_structure.md + db_descriptions.yaml
python scripts/00_inspect_db.py

# Use an alternate config / output / descriptions file
python scripts/00_inspect_db.py \
    --config config/config.yaml \
    --output db_structure.md \
    --descriptions db_descriptions.yaml
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--config PATH`        | `config/config.yaml`    | Path to the YAML config |
| `--output PATH`        | `db_structure.md`       | Path of the generated Markdown report |
| `--descriptions PATH`  | `db_descriptions.yaml`  | Path to the descriptions sidecar (read + written) |

---

## Example output

```text
Connecting to postgres@localhost:5433/cd48_demo...
Loaded D:\MyProject\69_CD48Processing\01_DEV\db_descriptions.yaml (existing).
Inspecting 3 schema(s): client, public, rendu
Wrote D:\MyProject\69_CD48Processing\01_DEV\db_structure.md (7,691 chars) and D:\MyProject\69_CD48Processing\01_DEV\db_descriptions.yaml.
```

The report itself opens with a metadata block (DB name, server version,
schemas inspected), then the `## About this database` section, then a
"## Overview" table (schema → table count → schema-exists flag), then a
per-schema detail section.

---

## Prerequisites

- Python deps: `psycopg2-binary`, `PyYAML` (see project `requirements.txt`).
- The DB user only needs `USAGE` on each inspected schema and `SELECT` on
  `pg_catalog` / `information_schema` (granted by default).
- No writes to the database — the script is read-only.

---

## Known issue / quirk

- **`session."geomCalibration"` carries SRID 0** in the current pipeline
  (latent bug in `scripts/01_copy_source_tables.py` — `ST_MakePointM`
  doesn't propagate SRID). `00_inspect_db.py` doesn't expose SRIDs in the
  Markdown table-column listing, so this isn't visible from the report;
  noting it here for completeness.

---

## Related files

- `config/config.yaml` — connection + the three schema names.
- `db_structure.md` — generated output (do not edit by hand — the script
  overwrites on every run).
- `db_descriptions.yaml` — **editable** source of truth for descriptions
  (preserved on every run).
- `scripts/01_copy_source_tables.py`, `scripts/02_step2_processing.py` —
  upstream pipeline steps that populate the schemas this script reports
  on. Run them first; then re-run `00_inspect_db.py` to see the updated
  structure.
