# `13_generate_pas.py`

Step 1.3 — builds fixed-step road segments (*pas*) from `client.troncon_client`,
restricted to the part that lies on an itinerary (`client.itineraires_v2`):

- **`client.pas_50`** — 50 m steps
- **`client.pas_100`** — 100 m steps

Columns (both tables): `id` (PK), `id_tronc`, `axe`, `cumuld`, `cumulf`,
`avg_width` (numeric), `surface` (numeric), `avg_note_global`,
`avg_note_structure`, `avg_note_surface` (numeric), `nb_pl_final`,
`nature_cr_final`, `geom` (`LineStringM, 2154` — the road line of the slice).

---

## How a row is built (per troncon)

1. **Intersecting part** — `itineraires_v2.geom` is re-projected to 2154; a
   troncon vertex counts as "on the itinerary" when it is within `--tol` m of
   that line. The covered cumul range `[a0, a1]` = min/max **M** of those
   vertices. (The troncon's own vertices are used because `ST_Intersection`
   **drops the M measure**.) Troncons with no covered vertex are skipped, and a
   troncon only partly on the itinerary is clipped to `[a0, a1]`.
2. **Steps** — from `a0`, increment by the step; `cumuld = round(a0 + k·step)`,
   `cumulf = round(min(a0 + (k+1)·step, a1))`. These are LRS cumul (= troncon
   `geom` M).
3. **geom** — `ST_GeometryN(ST_LocateBetween(troncon.geom, cumuld, cumulf), 1)`
   → `LineStringM, 2154` (the road line of the slice).
4. **avg_width** — `avg(public.image.measure_width)` over the images of that
   troncon with `image.cumuld BETWEEN cumuld AND cumulf` (non-null only). When a
   step has no images, falls back to a fixed *largeur*: **5.5 m**, or **7 m** for
   the structural network (`RD806` / `RD809`, matched as
   `RD806/RD809/078D0806/078D0809`).
5. **surface** — `(cumulf - cumuld) * COALESCE(avg_width, 5.5)` (m²).
6. **avg_note_global / avg_note_structure / avg_note_surface** —
   `avg(public.image.{note})` over the step's images (non-null only), where
   `{note}` is `note_globale` / `Note_Structure` / `Note_Surface`; falls back to
   **1.0** when a step has no images.
7. **id_tronc, axe, nb_pl_final, nature_cr_final** — carried from the troncon.

---

## Usage

```bash
python scripts/13_generate_pas.py            # builds pas_50 and pas_100
python scripts/13_generate_pas.py --tol 15 --dry-run
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | YAML config (`source:` block) |
| `--tol` | `15.0` | Distance (m) for a troncon vertex to count as on the itinerary |
| `--dry-run` | off | Print the SQL and exit without changes |

Runs in a single transaction; both tables are dropped + recreated with an `id`
PRIMARY KEY.

---

## Verified result

- `pas_50`: 1527 segments; `pas_100`: 781 — over the 8 itinerary axes.
- `geom` = `LineStringM, 2154`; 0 null geometries.
- 50 m stepping is contiguous per troncon (last step shorter), e.g. troncon 431
  → 0–50 … 2850–2863.
- Partial coverage honoured (078D0037 clipped to ~0–6900, not its full 0–15508).
- 295/1527 steps used the largeur fallback (no images).

---

## Prerequisites

- PostGIS; `client.troncon_client` (step 05) and `public.image.measure_width`
  (step 12) populated; `client.itineraires_v2` present.

## Related files

- `scripts/05_build_troncon.py` — the troncon source layer.
- `scripts/12_update_notes.py` — populates `image.measure_width`.
