# `04_make_finest_overlay.py`

Builds the **finest linear-referencing overlay** of two or more source layers
into one table. Every axe is split at the union of all segment boundaries so
each output segment carries exactly one combination of
`(axe, cumuld, cumulf, value_layer1, value_layer2, …)`.

Each source table shares the four columns `axe`, `cumuld`, `cumulf`, `geom`
and contributes **one considered-value column** (e.g. `nb_pl` for the traffic
layer, `nature_cr` for the road-surface layer).

Output table (default `client."20260301_trafic_couche_roulement_intersection"`)
columns: `id` (PRIMARY KEY), `axe`, `cumuld`, `cumulf`, `geom`, one column per
source named after its considered column (the raw overlay value), one
`<considered>_final` column per source (the post-processed, gap-filled value),
and the PR reference columns `plod`/`absd`/`plof`/`absf`.

## Post-processing (runs automatically after the overlay)

1. **Add `_final` columns** — for each source value column, add
   `<value>_final` and copy the raw overlay value into it.
2. **Fill `_final` nulls** — where a `<value>_final` is null, set it (per axe,
   one pass over the original values) from, in order:
   the **previous** segment, else the **next** segment, else the **nearest**
   non-null segment (nearest measured by `ST_Distance`, then cumul). Segments
   that have no value anywhere on their axe stay null (undeterminable).
3. **Fuse** — merge contiguous same-axe segments that share the same `_final`
   tuple into one row (geometry `ST_LineMerge(ST_Union(...))`, `cumuld`=min,
   `cumulf`=max); the element rows are dropped and the table is rebuilt with a
   fresh `id` PRIMARY KEY. The raw value columns are aggregated to the observed
   value (or null where it was inferred).
4. **PR reference columns** — add `plod`/`absd`/`plof`/`absf` and populate them
   from an anchor map of every source segment endpoint across **all** input
   tables (`(axe, cumuld) → plod/absd`, `(axe, cumulf) → plof/absf`), looking
   up the exact PR/abscissa at each fused segment's `cumuld` / `cumulf`. Skipped
   if any source lacks the four columns.

---

## Semantics

- **Union / outer** — a segment is emitted wherever *any* source table covers
  it. Stretches covered by only some layers appear with `null` for the others.
- Each minimal interval's **geometry** is the clipped geometry
  (`ST_LineSubstring`) of the **first listed table** that covers it (the
  "reference"); listing order therefore sets reference priority.
- A layer's value is attached to an interval only when its covering segment
  **geometrically matches** the reference — i.e. the majority of the reference
  geometry lies within `--geom-tol` metres of that segment
  (`ST_Length(ST_Intersection(ref, ST_Buffer(seg, tol))) > 0.5·length(ref)`).
  Otherwise the value is `null`. This matches segments on the LRS *and* on
  geometry while tolerating the small vertex differences `ST_LineMerge`
  introduces.
- If a layer has several covering, geometrically-matching segments over one
  interval, the output multiplies — one row per combination across layers (the
  "1 traffic × 2 surface ⇒ 2 rows" case). Identical compositions are collapsed
  (`DISTINCT`), and all-`null` rows are dropped.

> Note on the geometry test: a plain `ST_Length(ST_Intersection(seg, ref)) > 0`
> is **not** reliable here — GEOS returns length 0 for a segment intersected
> with a `ST_LineSubstring` of its own `ST_LineMerge` (collinear lines, slightly
> different vertices). The buffer/within test above avoids that.

---

## Usage

```bash
# The CD78 traffic × road-surface overlay (default output table)
python scripts/04_make_finest_overlay.py \
    --table 'client.20250916_trafic_most_recent:nb_pl' \
    --table 'client.20260227_couche_roulement:nature_cr'

# Custom output + matching tolerance, preview only
python scripts/04_make_finest_overlay.py \
    --table 'client.20250916_trafic_most_recent:nb_pl' \
    --table 'client.20260227_couche_roulement:nature_cr' \
    --output client.my_overlay --geom-tol 2.0 --dry-run
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--table SCHEMA.TABLE:VALUE_COL` | _(required, ≥2)_ | A source table and its considered-value column. Repeat; order = reference priority. |
| `--config PATH` | `config/config.yaml` | YAML config |
| `--axe-col` | `axe` | Axe column (shared by all tables) |
| `--cumuld-col` | `cumuld` | Cumul start column |
| `--cumulf-col` | `cumulf` | Cumul end column |
| `--geom-col` | `geom` | Geometry column |
| `--geom-tol` | `2.0` | Geometry matching tolerance (metres) |
| `--output schema.table` | `client."20260301_trafic_couche_roulement_intersection"` | Output table (dropped + recreated) |
| `--dry-run` | off | Print SQL and exit without changes |

If two source value columns share a name, later ones are suffixed (`_2`, …).

---

## How it works (SQL)

1. `bp` — every `cumuld`/`cumulf` of every table, per `axe`.
2. `iv`/`q` — consecutive breakpoints → minimal intervals `[a, b]`.
3. `r` — reference geometry per interval = `COALESCE` of the priority-ordered
   tables' clipped geometries (single-`LineString` segments only).
4. One `LEFT JOIN LATERAL` per table → covering + geometry-matching segments,
   cross-multiplying when a table has several. `SELECT DISTINCT` collapses
   identical compositions; all-null rows are filtered out.
5. `CREATE TABLE … AS SELECT row_number() … AS id, …` then
   `ADD PRIMARY KEY (id)`. Value columns keep their source types.
6. Post-processing steps 1–3 (above): add `_final` columns, fill nulls with
   window functions + a nearest-neighbour lateral lookup, then fuse via an
   islands-and-gaps grouping (`SUM` of a gap flag over `axe, _final…`).

---

## Verified result (CD78 traffic × couche_roulement)

- Overlay: **2993** rows (2272 both / 146 traffic-only / 575 surface-only, 0
  all-null).
- Post-processing: **721** `_final` nulls filled; fused down to **1635** rows.
- After fusion: unique `id` PK, 0 null geometries, **0** contiguous same-axe
  rows sharing a `_final` tuple, and **0** fillable `_final` nulls left (the
  185 `nb_pl_final` / 3 `nature_cr_final` remaining nulls are whole-axe cases
  with no value anywhere on the axe).

---

## Prerequisites

- PostGIS (`ST_LineMerge`, `ST_LineSubstring`, `ST_Buffer`, `ST_Intersection`).
- Each source table must have the four shared columns and its value column.
- Geometry direction assumed to increase with cumul (for `ST_LineSubstring`).

---

## Related files

- `overlapping_definition.md` — the overlap definitions.
- `scripts/03_take_most_recent_segment.py` — produces the de-overlapped
  `*_most_recent` layer used as a clean input here.
- `config/config.yaml` — DB connection.
