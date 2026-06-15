# `02_analyse_overlapping.py`

Read-only QA tool. Given a **source layer** (`schema.table`) in the PostgreSQL
database from `config/config.yaml`, it finds every pair of segments that
**overlap** and writes the result to a CSV + a Markdown summary.

It implements the two definitions in `overlapping_definition.md`:

1. **Geometry overlap** — segments `t1`, `t2` are on the same axe
   (`t1.axe = t2.axe`) and
   `ST_Length(ST_Intersection(t1.geom, t2.geom)) > --min-overlap` (default 1 m).
   A simple crossing (point intersection, length 0) is **not** flagged.
2. **Cumulated-distance overlap** — same axe and the cumul intervals
   `(t1.cumuld, t1.cumulf)` and `(t2.cumuld, t2.cumulf)` intersect over a
   non-zero range. Example: `(3, 15)` and `(10, 28)` overlap from `10` to `15`.

The script issues only `SELECT`s — it never writes to the database.

---

## What it does

For the chosen analysis type it self-joins the layer to itself on the axe
column with `id1 < id2` (so each pair appears once, and a segment is never
paired with itself).

**Geometry query** (per same-axe candidate pair):
```sql
... ST_Intersects(t1.geom, t2.geom)                       -- index-friendly pre-filter
WHERE ST_Length(ST_Intersection(t1.geom, t2.geom)) > :min_overlap
```

**Cumul query** — each segment's interval is normalised to `[lo, hi]` with
`lo = LEAST(cumuld, cumulf)`, `hi = GREATEST(cumuld, cumulf)` (robust to rows
where end is stored before start). Two intervals overlap when:
```sql
GREATEST(lo1, lo2) < LEAST(hi1, hi2)        -- strict: touching at a point is not an overlap
```
The reported `overlap_start = GREATEST(lo1, lo2)`,
`overlap_end = LEAST(hi1, hi2)`, `overlap_length = overlap_end - overlap_start`.

All table/column names come from CLI args and are quoted safely with
`psycopg2.sql.Identifier`, so unusual names like `20250916_trafic` work.

---

## Config keys used

Under `source:` in `config/config.yaml`:

| Key | Purpose |
|---|---|
| `host`, `port`, `user`, `password`, `database` | Connection parameters |

The schema and table come from `--source`, **not** from the config schema keys.

---

## Usage

```bash
# Both analyses on the trafic layer, default columns, default 1 m threshold
python scripts/02_analyse_overlapping.py --source client.20250916_trafic

# Include each segment's date (annee) in the output
python scripts/02_analyse_overlapping.py --source client.20250916_trafic --date-col annee

# Only the cumul analysis, custom output location
python scripts/02_analyse_overlapping.py --source client.20250916_trafic \
    --type cumul --output reports/trafic_overlap.csv

# Different column names / threshold
python scripts/02_analyse_overlapping.py --source public.road_data \
    --axe-col axe --cumuld-col cumuld --cumulf-col cumulf --geom-col geom \
    --min-overlap 2.0

# Preview the SQL without querying any data
python scripts/02_analyse_overlapping.py --source client.20250916_trafic --dry-run
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--source schema.table` | _(required)_ | Layer to analyse, e.g. `client.20250916_trafic` |
| `--config PATH` | `config/config.yaml` | Path to the YAML config |
| `--axe-col` | `axe` | Axe (route) column |
| `--cumuld-col` | `cumuld` | Cumul start column |
| `--cumulf-col` | `cumulf` | Cumul end column |
| `--geom-col` | `geom` | Geometry column |
| `--id-col` | `id` | Identifier column used to pair / de-duplicate |
| `--date-col` | _(none)_ | Optional date column (e.g. `annee`); when given, `t1_date` / `t2_date` are added to the output |
| `--type` | `both` | `geometry`, `cumul`, or `both` |
| `--min-overlap` | `1.0` | Geometry overlap threshold in metres |
| `--output PATH` | `overlapping_report.csv` | CSV path; a sibling `.md` is written next to it |
| `--dry-run` | off | Print the SQL and exit without querying |

---

## Output

Two files are written, both derived from `--output`. Results are merged so
there is **one row per `(axe, id1, id2)` pair**, with an `overlap_type` column
telling how the pair overlaps:

| `overlap_type` value | Meaning |
|---|---|
| `geometry` | Only the geometry analysis flagged the pair |
| `accumulated distance` | Only the cumul analysis flagged the pair |
| `both` | Flagged by both analyses |

- **`<output>.csv`** — columns:
  `overlap_type, axe, id1, id2, t1_cumuld, t1_cumulf, t2_cumuld, t2_cumulf,
  geom_overlap_length, cumul_overlap_start, cumul_overlap_end,
  cumul_overlap_length`.
  - `t1_date / t2_date` appear **only** when `--date-col` is given — the value
    of that column for each segment in the pair.
  - `t1_cumuld / t1_cumulf / t2_cumuld / t2_cumulf` are the raw cumul endpoints
    of each segment in the pair (always populated, whatever the overlap type).
  - `geom_overlap_length` (metres) is filled when geometry overlaps.
  - the three `cumul_overlap_*` columns (in cumul units) are filled when the
    cumul intervals overlap.
  - Columns not relevant to a row are left blank.
- **`<output>.md`** — a readable summary: header with the per-type counts +
  threshold, then a single table of all pairs.

Example (`reports/trafic_overlap.csv`):
```csv
overlap_type,axe,id1,id2,t1_cumuld,t1_cumulf,t2_cumuld,t2_cumulf,geom_overlap_length,cumul_overlap_start,cumul_overlap_end,cumul_overlap_length
geometry,078D0015,142,186,2186,3053,0,2186,6.841,,,
accumulated distance,078D0048,41,218,509,2584,607,2012,,607,2012,1405
both,078D0098,284,285,5722,7474,7437,11403,34.425,7437,7474,37
```

Note: when `--type` is `geometry` or `cumul`, only that analysis runs, so no
pair can be labelled `both`.

---

## Prerequisites

- Python 3.9+
- `psycopg2-binary`, `PyYAML` (see project `requirements.txt`)
- The DB must have **PostGIS** (uses `ST_Intersects`, `ST_Intersection`,
  `ST_Length`) for the geometry analysis. The cumul analysis needs no PostGIS.
- The DB user needs `USAGE` on the schema and `SELECT` on the layer.

---

## Notes

- The geometry length is measured in the units of the layer's SRID. The CD78
  layers use EPSG:3949 (metres), so the 1 m default threshold is in metres.
- Performance: the geometry self-join is `ST_Intersects`-pre-filtered and the
  axe equality narrows candidates heavily; for large layers a spatial index on
  the geometry column (`CREATE INDEX ... USING GIST (geom)`) makes it fast.

---

## Related files

- `overlapping_definition.md` — the two overlap definitions this script implements.
- `config/config.yaml` — DB connection parameters.
- `db_structure.md` — current DB structure (columns of the client layers).
