# `11_map_matching.py`

Assigns `id_tronc` and `axe` (plus the projection geometry / cumul) to every
point in **`public.image`** by map-matching it onto **`client.troncon_client`**.

Adapted from the RoadcareSig algorithm
(`55_RoadcareSigProd/01_DEV/roadcare_sig_prod/src/map_matching.py`) — the SQL
logic (10 steps) is unchanged; only the database wiring and column names were
changed for this project.

---

## What changed from the original

| Original | This project |
|---|---|
| connection from `config['target']` | `config/config.yaml` → `source:` block |
| `public.image.session_id` | `public.image."sessionId"` |
| `public.image.cumuld_session` | `public.image."cumulStartSession"` |
| `public.session.geom_calib` | `public.session."geomCalibration"` |
| `client.troncon_client.geom_calib` | `client.troncon_client.geom` (`LineStringM, 2154`) |
| `image.id_tronc` = `TEXT` | `image.id_tronc` = `BIGINT` (troncon PK type) |
| WIN1252/LATIN1 encoding retries | plain UTF-8 connect |

**SRID fix (Step 0):** `public.image.geom`, `public.session.geom` and
`public.session."geomCalibration"` are stored with **SRID 0** but hold
Lambert-93 (2154) coordinates. The script stamps SRID 2154 on them
(`ST_SetSRID`, coordinates unchanged, only when currently not 2154) so the
spatial joins with `troncon_client` (2154) and the 2154-typed output columns
work.

**`seg_ss` fix:** `ST_LocateBetween` on an M geometry returns `LINESTRINGM`, so
the original `GeometryType(...) = 'LINESTRING'` guard matched nothing here; the
check now wraps the geometry in `ST_Force2D` first (matching the `SET` clause).

---

## Output columns added to `public.image`

| Column | Type | Meaning |
|---|---|---|
| `id_tronc` | `BIGINT` | matched troncon (`client.troncon_client.id_tronc`) |
| `axe` | `TEXT` | axe of the matched troncon |
| `cumuld` | `NUMERIC` | LRS measure of the projected point (`ST_M`) |
| `prj_quality` | `NUMERIC` | projection distance (m) — smaller = better |
| `geom_prj` | `geometry(Point,2154)` | point projected onto the troncon |
| `ln_prj` | `geometry(LineString,2154)` | image-point → projection link |
| `seg_ss` | `geometry(LineString,2154)` | ±1 m session segment at the image |
| `seg_prj` | `geometry(LineString,2154)` | ±1 m troncon segment at the projection |
| `d_angle_seg` | `NUMERIC` | angle between `seg_ss` and `seg_prj` (perpendicular filter) |

Two working tables are (re)created in schema `traitement`:
`projection_paire` (session × troncon candidate pairs) and
`projection_img_dist` (image × pair distances).

---

## Algorithm (10 steps)

1. `seg_ss` — ±1 m slice of the session calibration line at each image's
   `cumulStartSession`.
2. `projection_paire` — session × troncon candidate pairs within the buffer,
   with overlap lengths and crossing angle.
3. Flag **valid** pairs (reject near-perpendicular 45–135° crossings and pairs
   with < `min_segment_length` overlap).
4. Reset image projection fields.
5. `projection_img_dist` — distance from each image to each valid pair's
   on-session geometry (small image buffer).
6. Assign the **nearest** troncon per image.
7. Projections: `cumuld` (`ST_M`), `geom_prj`, `ln_prj`, `seg_prj`,
   `d_angle_seg` (normalised).
8. Re-project images whose `seg`/`seg_prj` angle is perpendicular (45–135°)
   to the next-best non-perpendicular candidate — repeated
   `--perpendicular-iterations` times.
9. Final projections for the re-assigned images.
10. Set `axe` from the matched troncon.

---

## Usage

```bash
# Defaults: buffer 24 m, min segment 50 m, 2 perpendicular iterations
python scripts/11_map_matching.py

python scripts/11_map_matching.py \
    --buffer-radius 24 --min-segment-length 50 \
    --perpendicular-iterations 2 --config config/config.yaml --verbose
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `-c`, `--config` | `config/config.yaml` | YAML config (`source:` block) |
| `-b`, `--buffer-radius` | `24.0` | Buffer (m) for session/troncon matching |
| `-s`, `--min-segment-length` | `50.0` | Minimum valid overlap length (m) |
| `-i`, `--perpendicular-iterations` | `2` | Times to run perpendicular re-projection |
| `--srid` | `2154` | SRID of `troncon_client` / output projections |
| `-v`, `--verbose` | off | DEBUG logging |

---

## Verified result

- 12,378 images → **11,900 matched (96.14 %)**; all matched rows have
  `id_tronc`, `axe`, `cumuld`.
- 0 matched images missing `axe`; **0** `axe` mismatches vs `troncon_client`.
- Projection distance: avg ≈ 3.97 m, max ≈ 25 m (≈ buffer).

---

## Prerequisites

- PostGIS (`ST_LocateBetween`, `ST_LineLocatePoint`, `ST_LineInterpolatePoint`,
  `ST_M`, `ST_Buffer`, `ST_Angle`, …).
- `client.troncon_client` built first (see `scripts/05_build_troncon.py`) — its
  `geom` is `LineStringM, 2154` with M = cumul.
- `public.image` / `public.session` populated (see
  `scripts/01_copy_source_tables.py`).

---

## Related files

- `scripts/05_build_troncon.py` — produces the `troncon_client` reference layer.
- `config/config.yaml` — DB connection.
