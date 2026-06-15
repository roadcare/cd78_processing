# `01_copy_source_tables.py`

First step of the CD48 processing pipeline. Three phases:

1. **Copy** a fixed list of tables from the **original** schema to the
   **processing** schema, replacing any pre-existing target tables.
2. **PK-promote** each copied table — ensure `id` is `PRIMARY KEY`.
3. **Geometry calibration** — compute `image."geomCalibration"`,
   `session.geom`, and `session."geomCalibration"` from the freshly copied
   data (skipped if either `session` or `image` was omitted via `--tables`).

By default the copied tables are: `session`, `image`, `road_data`.

---

## What it does

For each table, in its own transaction:

```sql
DROP TABLE IF EXISTS <processing_schema>.<t> CASCADE;
CREATE TABLE <processing_schema>.<t>
        (LIKE <original_schema>.<t> INCLUDING ALL);
INSERT INTO <processing_schema>.<t>
       SELECT * FROM <original_schema>.<t>;
ANALYZE <processing_schema>.<t>;
-- then: ensure_id_primary_key(<processing_schema>, <t>)  -- see below
```

- `LIKE ... INCLUDING ALL` preserves data types, NOT NULL, defaults, primary
  keys, indexes, and check constraints. Foreign keys are **not** copied
  (Postgres limitation), which is moot here because the source schema has none.
- `DROP ... CASCADE` removes the target along with any dependent objects
  (views, downstream constraints). This makes the script safely re-runnable
  once later steps add dependents.
- `ANALYZE` is run so the planner has fresh stats immediately.
- The PK-promotion step runs in the **same** transaction as the copy — so the
  target table is always either "copied and PK'd" or rolled back to its prior
  state.
- Each table runs in its own transaction. A failure mid-copy leaves the other
  tables in their previous state.

### `id` primary-key policy (idempotent)

After the copy, the script promotes `id` to PRIMARY KEY according to this
table:

| State of target after copy                 | Action                                               | Log message                          |
|---|---|---|
| Already has PK on `(id)`                   | no-op                                                | `kept: PK(id)`                       |
| Has PK on other column(s)                  | left alone (source intent preserved)                 | `kept: PK(<cols>)`                   |
| No PK; `id` exists and is NOT NULL         | `ALTER TABLE … ADD PRIMARY KEY (id)`                 | `added: PK(id)`                      |
| No PK; `id` exists and is NULLABLE         | `SET NOT NULL` on `id`, then add PK                  | `added: PK(id) (forced NOT NULL)`    |
| No PK; no `id` column at all               | `ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` | `added: synthetic id (BIGINT identity) + PK` |

For the CD48 default tables this means:
- `road_data` — source already has PK on `id` → kept untouched.
- `session`, `image` — source has no PK → `id` is promoted to PK.

---

## Geometry calibration step

After all tables have been copied and PK-promoted, the script runs three
`UPDATE`s (in a single transaction) to compute calibration geometry, sourced
from `task/example_calculate_geoCalibration.md`:

```sql
-- 1) Point-M per image: XY from image.geom, M from cumulStartSession
UPDATE <processing_schema>.image
   SET "geomCalibration" =
       ST_MakePointM(ST_X(geom), ST_Y(geom), "cumulStartSession"::numeric);

-- 2) session.geom = simplified LineString of ordered image points
UPDATE <processing_schema>.session t1
   SET geom = ST_Simplify(<LineString from ordered image.geom>, 0.5)
 WHERE r2."sessionId" = t1.id;

-- 3) session."geomCalibration" = LineString of ordered image PointMs
UPDATE <processing_schema>.session t1
   SET "geomCalibration" = <LineString from ordered image."geomCalibration">
 WHERE r2."sessionId" = t1.id;
```

Notes:
- Only runs when **both** `session` and `image` are in the requested `--tables`.
  Otherwise the step is skipped with a clear log message.
- Runs in a single transaction; partial failure leaves the geometry columns in
  their post-copy state (i.e. as copied from the source schema).
- Camel-case `"geomCalibration"` is preserved (no rename).
- Order inside the aggregate `ST_MakeLine` is provided by an inner
  `ORDER BY "sessionId", "cumulStartSession"` — Postgres respects that order
  for the aggregate input in practice. If correctness ever drifts, the
  strictly-guaranteed form is `ST_MakeLine(geom ORDER BY ...)`.

---

## Prerequisites

- Python 3.9+
- `psycopg2-binary`, `PyYAML` (see project `requirements.txt`)
- A populated `config/config.yaml`
- The user in `config.yaml` must have:
  - `USAGE` on the original schema and `SELECT` on the source tables.
  - `CREATE` on the processing schema (to recreate the tables).

---

## Config keys used

Read from `config/config.yaml` under the top-level `source:` block:

| Key | Purpose |
|---|---|
| `host`, `port`, `user`, `password`, `database` | Connection parameters |
| `original_schema` | Source schema (e.g. `fromrcweb`) |
| `processing_schema` | Target schema (e.g. `public`) |

If `original_schema == processing_schema`, the script refuses to run and exits
with code `2` — it won't copy a schema onto itself.

---

## Usage

```bash
# Normal run — copies session, image, road_data
python scripts/01_copy_source_tables.py

# Preview the exact SQL without touching the DB
python scripts/01_copy_source_tables.py --dry-run

# Override the list of tables
python scripts/01_copy_source_tables.py --tables session,image

# Use an alternate config file
python scripts/01_copy_source_tables.py --config path/to/other.yaml
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | Path to the YAML config |
| `--tables a,b,c` | `session,image,road_data` | Comma-separated list of table names to copy |
| `--dry-run` | off | Print the SQL that would run, then exit without changes |

---

## Behavior details

### Pre-flight check
Before dropping anything, the script verifies that **every** requested table
exists in the original schema. If any table is missing, it exits with code `3`
and makes no changes. This prevents a typo in `--tables` from dropping the
target half-way through.

### Transaction scope
One transaction **per table**:
- If `road_data` fails to copy, the `session` and `image` tables that ran
  earlier are already committed; they are not rolled back.
- If you want all-or-nothing, run with `--dry-run` first, then run for real.

### Row-count verification
After each copy, the script prints:
```
src rows: 62,296  dst rows: 62,296  (4.97s)
```
A mismatch is reported as a warning and the process exits with code `1` at
the end (after still attempting the remaining tables).

### What survives the copy

| Object | Copied? |
|---|:---:|
| Column types | yes |
| NOT NULL | yes |
| Defaults | yes |
| Primary key | yes (and **forced** to `(id)` if source had none — see policy above) |
| Unique constraints | yes |
| Check constraints | yes |
| Indexes | yes |
| **Foreign keys** | **no** (Postgres `LIKE` limitation) |
| Triggers | no |
| Comments | no |
| Permissions / grants | no |

In the CD48 source schema (`fromrcweb`) only `road_data` has a primary key
declared; none of the source tables have FKs or triggers. After this script
runs, all three default targets in `public` end up with a PK on `id`.

---

## Exit codes

| Code | Meaning |
|:---:|---|
| `0` | Success |
| `1` | At least one table copied but row counts didn't match |
| `2` | `original_schema == processing_schema` — refused to run |
| `3` | One or more requested tables missing in the source schema |

(Any uncaught exception, e.g. connection failure, exits with a non-zero code
and a Python traceback.)

---

## Example output

```text
DB: postgres@localhost:5433/cd48_demo
Copying fromrcweb -> public: session, image, road_data

--- public.session ---
  src rows: 20  dst rows: 20  PK: added: PK(id)  (0.10s)

--- public.image ---
  src rows: 31,568  dst rows: 31,568  PK: added: PK(id)  (1.22s)

--- public.road_data ---
  src rows: 62,296  dst rows: 62,296  PK: kept: PK(id)  (5.10s)

--- geometry calibration ---
  image.geomCalibration       updated: 31,568
  session.geom                updated: 20
  session.geomCalibration     updated: 20  (1.25s)

Done.
```

---

## Re-running

Safe to re-run any time. Each run fully replaces the target tables, so the
processing schema is reset to a clean copy of the source. Anything downstream
that depended on those tables will be dropped by `CASCADE` — you'll need to
re-build views or materialized views that other pipeline steps had added.

---

## Related files

- `config/config.yaml` — connection + schema names.
- `scripts/00_inspect_db.py` — generates `db_structure.md` from the *processing*,
  *client*, and *reporting* schemas; useful for confirming the copy worked.
- `db_structure.md` — current report of the inspected schemas.
- `db_descriptions.yaml` — hand-written table/column descriptions (preserved
  across `00_inspect_db.py` re-runs).
