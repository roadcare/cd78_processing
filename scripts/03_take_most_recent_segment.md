# `03_take_most_recent_segment.py`

Resolves overlapping segments in a source layer so the **most recent** segment
wins, and writes the de-overlapped result to a new table
(default `<input_table>_most_recent`, same schema).

The output table has:
- a fresh **`id`** — `bigint GENERATED ALWAYS AS IDENTITY`, the unique
  **PRIMARY KEY**;
- **`source_id`** — the original source `id` (kept for traceability; **not**
  unique, since a clipped segment may appear on more than one row);
- **`is_overlapping`** — boolean flag (default `false`);
- every other source column, unchanged.

Overlap follows `overlapping_definition.md`:
- **geometry**: same axe and `ST_Length(ST_Intersection) > --min-overlap` m.
- **cumulated distance**: same axe and the `(cumuld, cumulf)` intervals
  intersect over a non-zero range.

---

## Rules

Recency comes from `--date-col` (e.g. `annee`). Values are compared directly;
**NULL counts as 0**; ties are broken by larger `id` = newer.

| Situation | Output |
|---|---|
| Segment in no overlap | copied as-is, `is_overlapping = false` |
| Pair overlaps in **geometry** (with or without cumul) | newer kept unchanged; **older clipped** to the part not covered by the newer |
| Pair overlaps in **cumulated distance only** (geometries apart) | **both** copied unchanged, `is_overlapping = true` (flagged for review) |

### How the older segment is clipped

- **Overlap in both geometry + cumul** — the newer partner's cumul interval is
  removed from the older's `[cumuld, cumulf]`. Each surviving sub-interval
  becomes one output row whose geometry is the matching slice of the older line
  (`ST_LineSubstring`), **then** the geometry of every newer geometry-overlapping
  partner (both- *and* geometry-only partners of this older) is subtracted from
  that slice. `cumuld` / `cumulf` are the sub-interval bounds. This guarantees
  the kept part overlaps no newer segment in **either** sense — even when the
  line is not perfectly proportional to cumul (real data is often offset, so the
  geometry subtraction is what actually removes the spatial overlap). Pieces
  shorter than `--min-overlap` are dropped. A newer segment in the middle of the
  older yields **two** rows.
  - Fallback: if the older geometry does not merge to a single `LineString`,
    the script falls back to the geometry-difference method below (cumul left
    as-is) and logs a `WARN`.
- **Overlap in geometry only** — geometry = `ST_Difference(older, newer)`
  (`ST_CollectionExtract(...,2)` + `ST_Multi` keep it a clean MultiLineString);
  `cumuld` / `cumulf` are left unchanged. One row.

Because a clipped segment may legitimately appear on more than one row (middle
split) or be modified, the source primary key is not reused: the table is built
with `CREATE TABLE ... (LIKE src)` (columns/types/NOT NULL only), the source
`id` is renamed to `source_id`, and a brand-new generated `id` becomes the
unique PRIMARY KEY. `source_id` ties each output row back to its origin.

---

## Config keys used

Under `source:` in `config/config.yaml`: `host`, `port`, `user`, `password`,
`database`. Schema/table come from `--source` and `--output`.

---

## Usage

```bash
# Default: build client.20250916_trafic_most_recent
python scripts/03_take_most_recent_segment.py \
    --source client.20250916_trafic --date-col annee

# Custom output table + threshold
python scripts/03_take_most_recent_segment.py \
    --source client.20250916_trafic --date-col annee \
    --output client.trafic_clean --min-overlap 1.0

# Preview the SQL without changing the database
python scripts/03_take_most_recent_segment.py \
    --source client.20250916_trafic --date-col annee --dry-run
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--source schema.table` | _(required)_ | Source layer |
| `--date-col` | _(required)_ | Recency column (e.g. `annee`) |
| `--output schema.table` | `<source>_most_recent` | Output table (same schema by default) |
| `--config PATH` | `config/config.yaml` | YAML config |
| `--axe-col` | `axe` | Axe column |
| `--cumuld-col` | `cumuld` | Cumul start column |
| `--cumulf-col` | `cumulf` | Cumul end column |
| `--geom-col` | `geom` | Geometry column |
| `--id-col` | `id` | Identifier column |
| `--min-overlap` | `1.0` | Geometry overlap threshold (metres) |
| `--dry-run` | off | Print SQL and exit without changes |

---

## Behaviour notes

- Everything runs in **one transaction**; on any error nothing is committed.
- The output table is **dropped and recreated** on each run (`DROP ... CASCADE`).
- Length/overlap are in the layer's SRID units; CD78 uses EPSG:3949 (metres).
- Geometry direction is assumed to increase with cumul (standard linear
  referencing) for `ST_LineSubstring`.
- A segment that is simultaneously a "both"-overlap older **and** a
  geometry-only older has the geometry of *all* its newer geometry-overlapping
  partners subtracted (the geometry-only partners are folded into the same
  clip), so no geometric overlap survives.

---

## Verified result (`client.20250916_trafic`, `--date-col annee`)

- 506 source rows → **505** output rows.
- 1 pair fully covered (older dropped), 2 "both" + 2 geometry-only olders
  clipped, 1 cumul-only pair flagged (`is_overlapping = true`).
- Re-checking the output: **0** remaining geometry overlaps > 1 m.

---

## Related files

- `overlapping_definition.md` — the overlap definitions.
- `scripts/02_analyse_overlapping.py` — reports overlaps (use to inspect a layer
  before/after).
- `config/config.yaml` — DB connection.
