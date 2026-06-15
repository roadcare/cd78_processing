# `05_build_troncon.py`

Builds **`client.troncon_client`** from the step-0.4 overlay table
(`client."20260301_trafic_couche_roulement_intersection"`): one clean,
M-calibrated `LineString` per road *troncon*.

For every source row:

1. **Fuse** — `ST_LineMerge(geom)` collapses a contiguous MultiLineString into a
   single LineString.
2. **Decompose** — `ST_Dump` splits the result into individual LineStrings. Per
   piece, `cumuld`/`cumulf` are split **proportionally by length** (component
   order), and the PR references are updated:
   - first piece keeps the row's `plod`/`absd`, last keeps `plof`/`absf`;
   - interior boundary abscissae are interpolated **linearly by cumul**
     (`plo` carries `plod` — approximate where a piece crosses a PR reset);
   - single-piece rows are unchanged.
3. **Write** — to the output table with a new `id_tronc` PRIMARY KEY. `geom`
   becomes `geometry(LineStringM, <srid>)` (default **2154**), built as
   `ST_AddMeasure(ST_Transform(geom, <srid>), cumuld, cumulf)` — the
   `ST_Transform` is applied only when the source SRID differs from the target.
   The M value therefore equals the cumul (LRS) measure at every vertex.

All other source columns (`axe`, the value columns, the `_final` columns, the
original `id`, …) are carried over unchanged. The source `id` is kept as a
plain column for traceability (not unique — a multi-part row yields several
troncons sharing it).

Two derived length columns are also added:
- **`len_shp`** (`numeric`) = `ST_Length(geom)` — geometric length in the target
  SRID (metres).
- **`len_cumul`** (`bigint`) = `abs(cumulf - cumuld)` — the LRS span. Comparing
  the two flags calibration drift between the geometry and the linear measure.

### PR-boundary correction

Finally, a correction enforces that **successive** segments of an axe agree at
their shared boundary: if `t2.cumuld = t1.cumulf` then `t2.plod/absd` should
equal `t1.plof/absf`. Where they disagree, the side whose PR position
`plo*1000 + abs` is **closest to the cumul** wins and is copied to the other
side (`plod` is text → non-numeric values treated as 0; predecessor found by
`LAG` over `axe ORDER BY cumuld, cumulf, id_tronc`). The decision is
materialised in a temp table first so both updates use the original values.

---

## Usage

```bash
# Default: client."20260301_trafic_couche_roulement_intersection" -> client.troncon_client
python scripts/05_build_troncon.py

# Custom source/output/target SRID, or preview the SQL
python scripts/05_build_troncon.py \
    --source client.20260301_trafic_couche_roulement_intersection \
    --output client.troncon_client --target-srid 2154 --dry-run
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--source schema.table` | `client.20260301_trafic_couche_roulement_intersection` | Step-0.4 overlay table |
| `--output schema.table` | `client.troncon_client` | Output table (dropped + recreated) |
| `--target-srid` | `2154` | SRID of the output `geom` (Lambert-93) |
| `--config PATH` | `config/config.yaml` | YAML config |
| `--geom-col` / `--cumuld-col` / `--cumulf-col` | `geom` / `cumuld` / `cumulf` | LRS columns |
| `--plod-col` / `--absd-col` / `--plof-col` / `--absf-col` | `plod` / `absd` / `plof` / `absf` | PR reference columns |
| `--id-col` | `id` | Source identifier (groups a row's pieces) |
| `--dry-run` | off | Print SQL and exit without changes |

---

## How it works (SQL)

1. `dumped` — `ST_Dump(ST_LineMerge(geom))` per source row (`CROSS JOIN
   LATERAL`), keeping each piece's path index and length.
2. `calc` — window sums per source `id`: total length, length-before-this-piece,
   piece count.
3. `geo` — proportional `cumuld`/`cumulf` (`_cd`/`_cf`) per piece.
4. `geo2` — interpolated `absd`/`absf` and the `plof` (exact on the last piece,
   else `plod`).
5. Final `SELECT` — `id_tronc = row_number()`, every source column (cumul / PR /
   geom swapped for the recomputed values), then
   `CREATE TABLE … AS`, force the column type to `geometry(LineStringM, srid)`,
   and `ADD PRIMARY KEY (id_tronc)`.

---

## Verified result

- 1635 source rows → **2064** troncons (multi-part rows decomposed).
- `geom` is `LineString` **M**, SRID **2154** on every row.
- Start M = `cumuld` and end M = `cumulf` on **all** rows.
- Unique `id_tronc` PK; decomposed pieces are contiguous and span the original
  cumul range (e.g. source id 2, `150→806`, split into 5 contiguous pieces).
- PR-boundary correction: 399 mismatched boundaries fixed (135 next-fixed, 264
  prev-fixed) → **0** successive boundaries remain inconsistent.

---

## Prerequisites

- PostGIS (`ST_LineMerge`, `ST_Dump`, `ST_Transform`, `ST_AddMeasure`).
- The target/source SRIDs must exist in `spatial_ref_sys` (2154 and 3949 do).

---

## Related files

- `scripts/04_make_finest_overlay.py` — produces the source overlay table.
- `config/config.yaml` — DB connection.
