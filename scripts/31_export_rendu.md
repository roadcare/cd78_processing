# `31_export_rendu.py`

Tasks 3.1 / 3.2 — export the *rendu* layers to GeoJSON, an Excel workbook, and a
self-contained Leaflet viewer, into `--out` (default `D:\Tmp\cd78_exports`).

## 3.1 — GeoJSON (`<layer>.geojson`, EPSG:4326)

| Layer | Source | Notes |
|---|---|---|
| `troncon_client` | `client.troncon_client` | |
| `itineraires_v2` | `client.itineraires_v2` | |
| `pas_50` / `pas_100` | `client.pas_50` / `pas_100` | drops `avg_note_global` (note globale /1) and `Note_globale` (/20); `Etat_global` kept |
| `session` | `public.session` | drops `geomCalibration, surfaceGrade, structuralGrade, calibrationId, calibrationError, calibrationErrorMailSent, calibrationDone, videoToImagesDone, metadataId, state` |
| `image` | `public.image` | drops `geomCalibration, cumulEndSession, prIdStart, prDistanceStart, elapsedTime, road_cumul, road_id, geom_prj, ln_prj, seg_ss, seg_prj, d_angle_seg, geom_visible` |
| `road_data` | `public.road_data` | `WHERE classe IN ('Dégradation chaussée','Largeur')`; drops `pixels_coords` |

Every geometry is `ST_Transform`-ed to 4326 (SRID 0 is assumed 2154), with
coordinates capped at 6 decimals. All **floating-point attributes** (`numeric`,
`float8`, `float4` — notes, `avg_width`, `surface`, …) are **rounded to 2
decimals** in the GeoJSON and the viewer/popup (Excel keeps full precision).
Dropping the other geometry columns leaves a single geometry per feature. Rows
with **null/empty geometry are excluded**
(e.g. `road_data` `Largeur` rows have no `geom`) — otherwise Leaflet throws
`Invalid LatLng (undefined, undefined)` on the coordinate-less feature.

## Excel (`pas.xlsx`)

Two sheets — **`pas_50`** and **`pas_100`** — with the attribute columns (24).
The `geom`, `avg_note_global` and `Note_globale` columns are **not** exported.

## 3.2 — Dashboard (`index.html` + `<layer>.js`)

A Leaflet + [Chart.js] dashboard. Only the **three** layers `pas_100`,
`troncon_client` and `road_data` are included — each is written as `<layer>.js`
(`var LAYER_<name> = <geojson>;`) and loaded via `<script>`, so the viewer works
straight from `file://` (a `fetch` of local GeoJSON is blocked by browsers). The
other `.geojson` files are still produced by 3.1 but are not loaded by the page.

Layout: a left **sidebar** (logo + analysis) and the **map**.

- **Logo** — `config.yaml` `html: logo_path` is copied next to `index.html` as
  `logo.<ext>` and shown in the header.
- **KPIs** (recomputed on every filter): segment count, linéaire (km),
  budget (€ = Σ `Cout_Total`).
- **Cross-filters** that drive both the map (`pas_100`) and the charts:
  `Axe`, `Priorité`, `Type de chaussée`, `Importance trafic`, `État global`,
  `Technique d'entretien` (dropdowns auto-filled from the data) + a free-text
  search (Enter). A *Réinitialiser* button clears them (and re-fits the map to
  the whole network). **Choosing an `Axe` recentres/zooms the map on that axe.**
- **Charts** (Chart.js), all on the filtered `pas_100`:
  1. *États* — grouped bar of `Etat_surface` / `Etat_structure` / `Etat_global`
     over A-Bon / B-Moyen / C-Mauvais (the **Note Surface / Structure / Global**
     dimensions). The y axis is the **total length (m)** of the segments in each
     état (Σ `cumulf − cumuld`), not the segment count.
  2. *Budget par priorité* — Σ `Cout_Total` by `Priorite`.
  3. *Type de travaux* — segment count by `Technique_entretien`.
  4. *Budget par technique* — Σ `Cout_Total` by `Technique_entretien`.
- **Map** — `pas_100` is coloured by **`Etat_surface`** (A-Bon = green,
  B-Moyen = yellow, C-Mauvais = red). Each segment that needs work also carries a
  permanent **label** "`Priorite · Technique_entretien`" (e.g. `P1 · Rabotage +
  4 BBM`), shown only at zoom ≥ `html: pas_label_zoom_min` (default 17) to avoid
  clutter; `-` (no work) segments are unlabelled. `troncon_client` (line) and
  `road_data` (centroid points)
  are toggleable context layers showing all features. **`road_data` is off by
  default** (toggle it on in the layer control) — it is the heaviest layer, so
  the map loads faster without it.
- Layer-control names: `troncon_client` → **`ref_cd78`**, `pas_100` →
  **`Etat et travaux`**, `road_data` → **`degradations`** (full **multipolygon
  `geom`**, not centroids, off by default).
- The `degradations` popup shows the photo only — the long `filename` URL text
  row is hidden (as are `image_url` and `Etat_global` on `pas_100`).
- **Popups** show a picture: `degradations` (road_data) → its own `filename`
  photo; **`pas_100` → a
  representative image** computed at export — the `public.image` on the same
  `axe` within `[cumuld, cumulf]` whose `note_globale` is closest to the pas'
  `avg_note_global`. Its `url` becomes the `image_url` property (hidden from the
  attribute table, used for the `<img>`). 763/781 pas have one.
  `Etat_global` is hidden from the pas popup (kept for the filter/chart).
- The `degradations` sidecar keeps the **full polygons** and only the
  `classe`, `sous_classe`, `filename` properties (the bulky/irrelevant fields
  are dropped) — ≈ 47 MB; it is off by default to keep the map responsive.

**Offline-safe libraries.** Leaflet and Chart.js are **vendored** into
`out_dir/lib/` at export time and referenced with relative paths, so the page
needs no CDN (only the map *tiles* still need internet). If the export machine
can't download them, the page falls back to the CDN URLs and a warning is
printed. A red banner appears in the page if a library still fails to load
(instead of a silently blank page).

[Chart.js]: bundled in `lib/chart.umd.min.js`.

## Usage

```bash
python scripts/31_export_rendu.py                 # geojson + js + html + xlsx
python scripts/31_export_rendu.py --geojson-only  # only the .geojson files
python scripts/31_export_rendu.py --excel-only    # only pas.xlsx
python scripts/31_export_rendu.py --html-only     # only the dashboard (js + html)
python scripts/31_export_rendu.py --out D:\Tmp\cd78_exports
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | YAML config (`source:` + `html:`) |
| `--out DIR` | `D:\Tmp\cd78_exports` | Output folder (created if missing) |
| `--geojson-only` | off | Only write the `.geojson` files |
| `--excel-only` | off | Only write `pas.xlsx` |
| `--html-only` | off | Only (re)build the viewer: `index.html` + viewer `.js` sidecars + logo/libs (skips `.geojson` files and Excel; touches only the 3 viewer layers) |

## Verified result

- Layers exported: troncon 2064, itineraires 8, pas_50 1527, pas_100 781,
  session 14, image 12378, road_data 58243 (4326; excluded columns absent;
  `road_data` has no `pixels_coords`; classe filter applied; null/empty geom
  dropped — 69671 → 58243).
- Rendered headless (Chrome): no error banner, filters populated (5/8/4
  options), KPIs 781 / 74.7 km / 3 296 500 €, tiles + 4 charts drawn.
- `pas.xlsx`: sheets `pas_50` (1527) / `pas_100` (781), **no `geom`** column
  (26 columns each).
- `index.html` loads only the 3 viewer sidecars (`pas_100`, `troncon_client`,
  `road_data`) + the copied `logo.svg`; KPIs, 5 cross-filters and 4 charts wired
  to the filtered `pas_100`.

## Notes

- `road_data` is large (≈77 MB GeoJSON: 58k detailed polygons). The viewer copy
  is centroids with `filename` + uuids dropped → `road_data.js` ≈ 18 MB (was
  ≈42 MB); toggle it off for a snappier map.
- Only viewer layers get a `.js` sidecar; the run also deletes orphan sidecars
  left by older versions.
- Leaflet + Chart.js are vendored to `lib/` (no CDN needed); only the basemap
  tiles require internet.
- `pandas.read_sql` over a psycopg2 connection emits a harmless SQLAlchemy
  UserWarning.

## Related files

- `config/config.yaml` — DB connection + `html:` (tiles, attribution).
- The layers come from steps 03 / 04 / 05 / 06 / 11 / 12.
