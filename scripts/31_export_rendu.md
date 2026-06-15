# `31_export_rendu.py`

Tasks 3.1 / 3.2 — export the *rendu* layers to GeoJSON, an Excel workbook, and a
self-contained Leaflet viewer, into `--out` (default `D:\Tmp\cd78_exports`).

## 3.1 — GeoJSON (`<layer>.geojson`, EPSG:4326)

| Layer | Source | Notes |
|---|---|---|
| `troncon_client` | `client.troncon_client` | |
| `itineraires_v2` | `client.itineraires_v2` | |
| `pas_50` / `pas_100` | `client.pas_50` / `pas_100` | |
| `session` | `public.session` | drops `geomCalibration, surfaceGrade, structuralGrade, calibrationId, calibrationError, calibrationErrorMailSent, calibrationDone, videoToImagesDone, metadataId, state` |
| `image` | `public.image` | drops `geomCalibration, cumulEndSession, prIdStart, prDistanceStart, elapsedTime, road_cumul, road_id, geom_prj, ln_prj, seg_ss, seg_prj, d_angle_seg, geom_visible` |
| `road_data` | `public.road_data` | `WHERE classe IN ('Dégradation chaussée','Largeur')`; drops `pixels_coords` |

Every geometry is `ST_Transform`-ed to 4326 (SRID 0 is assumed 2154), with
coordinates capped at 6 decimals. Dropping the other geometry columns leaves a
single geometry per feature.

## Excel (`pas.xlsx`)

Two sheets — **`pas_50`** and **`pas_100`** — with all columns; `geom` is
written as WKT text so the sheet stays flat.

## 3.2 — Leaflet viewer (`index.html` + `<layer>.js`)

Each layer is also written as `<layer>.js` (`var LAYER_<name> = <geojson>;`) and
loaded by `index.html` via `<script>` — so the viewer works straight from
`file://` (a `fetch` of local GeoJSON is blocked by browsers). Tiles /
attribution come from `config.yaml` `html:`.

- **Default-visible**: `pas_100`, `troncon_client`, `road_data`, `image`. All
  layers are toggleable via the layer control; a text box filters every layer
  by a substring of its properties (press Enter).
- **Popups** for `image` and `road_data` show the picture (`filename`) as a
  thumbnail/link.
- The viewer copies are lightened so the map stays responsive: `road_data` is
  reduced to **centroid points** with the heavy/irrelevant columns dropped
  (`pixels_coords` is already excluded; the viewer also drops `comment`,
  `sessionName`, `sessionId`, `image_id`). The full polygons remain in
  `road_data.geojson`.

## Usage

```bash
python scripts/31_export_rendu.py                 # geojson + js + html + xlsx
python scripts/31_export_rendu.py --geojson-only  # only the .geojson files
python scripts/31_export_rendu.py --excel-only    # only pas.xlsx
python scripts/31_export_rendu.py --out D:\Tmp\cd78_exports
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | YAML config (`source:` + `html:`) |
| `--out DIR` | `D:\Tmp\cd78_exports` | Output folder (created if missing) |
| `--geojson-only` | off | Only write the `.geojson` files |
| `--excel-only` | off | Only write `pas.xlsx` |

## Verified result

- Layers exported: troncon 2064, itineraires 8, pas_50 1527, pas_100 781,
  session 14, image 12378, road_data 69671 (4326; excluded columns absent;
  `road_data` has no `pixels_coords`; classe filter applied).
- `pas.xlsx`: sheets `pas_50` (1527) / `pas_100` (781), geom as WKT.
- `index.html` loads the `.js` sidecars (works from `file://`); default layers
  visible; layer toggle + filter + image popups.

## Notes

- `road_data` is large (≈77 MB GeoJSON: 58k detailed polygons). The viewer copy
  (centroids, ≈42 MB — dominated by the per-row image SAS-URLs) keeps it usable;
  consider toggling it off for a snappier map.
- `pandas.read_sql` over a psycopg2 connection emits a harmless SQLAlchemy
  UserWarning.

## Related files

- `config/config.yaml` — DB connection + `html:` (tiles, attribution).
- The layers come from steps 03 / 04 / 05 / 06 / 11 / 12.
