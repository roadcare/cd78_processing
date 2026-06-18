# `12_update_notes.py`

Step 1.2 — populates degradation **notes** on `public.image` from
`fromrcweb.image_grade`, then derives two composite notes.

## What it does

1. Adds **26** `"Note_<DEGRADATION>"` numeric columns (`ADD COLUMN IF NOT EXISTS`).
2. Fills them from `image_grade."referenceGrades"` (a `jsonb` map of
   `degradation → grade`), matched by `image.id = image_grade."imageId"::uuid`:

   ```
   "Note_<X>" = COALESCE((referenceGrades ->> '<X>')::numeric, 1.0)
   ```

   So a present key takes its grade; an **absent key**, an empty `{}`, a null
   `referenceGrades`, or an image with **no grade row** all default to **1.0**
   (no degradation). A single `LEFT JOIN` + `COALESCE` covers every case.
3. Adds `Note_Structure` and `Note_Surface` (numeric) and sets them to the
   product of `power(Note_x, exponent)` (the task's `**` → SQL `power()`):

   - **Note_Structure** = `power(Note_AFFAISSEMENT_SIGNIFICATIF,0.8) *
     power(Note_AFFAISSEMENT_GRAVE,1.0) * power(Note_ORNIERAGE_SIGNIFICATIF,0.8) *
     power(Note_ORNIERAGE_GRAVE,1.0) * power(Note_FAIENCAGE_SIGNIFICATIF,1.0) *
     power(Note_FAIENCAGE_GRAVE,1.0) * power(Note_FAIENCAGE_BDR,1.0) *
     power(Note_FISSURE_LONGITUDINALE_GRAVE,1.0) *
     power(Note_FISSURE_LONGITUDINALE_BDR,1.0) *
     power(Note_FISSURE_LONGITUDINALE_PONTEE,0.1) *
     power(Note_FISSURE_TRANSVERSALE_GRAVE,1.0) *
     power(Note_FISSURE_TRANSVERSALE_PONTEE,0.1) *
     power(Note_REPARATION_PETITE_LARGEUR,0.1) *
     power(Note_REPARATION_PLEINE_LARGEUR,0.1) *
     power(Note_JOINT_LONGITUDINAL,0.1) * power(Note_JOINT_TRANSVERSAL,0.1) *
     power(Note_FISSURE_TRANSVERSALE_SIGNIFICATIVE,0.8) *
     power(Note_FISSURE_LONGITUDINALE_SIGNIFICATIVE,0.2)`
   - **Note_Surface** = `power(Note_ARRACHEMENT_SURFACE,0.7) *
     power(Note_ARRACHEMENT_PROFOND,0.9) * power(Note_NID_DE_POULE,1.0) *
     power(Note_FAIENCAGE_SIGNIFICATIF,1.0) * power(Note_FAIENCAGE_GRAVE,1.0) *
     power(Note_FISSURE_LONGITUDINALE_SIGNIFICATIVE,0.8) *
     power(Note_FISSURE_LONGITUDINALE_GRAVE,1.0) *
     power(Note_FISSURE_TRANSVERSALE_SIGNIFICATIVE,0.2) *
     power(Note_GLACAGE_RESSUAGE_LOCALISE,0.2) *
     power(Note_GLACAGE_RESSUAGE_GENERALISE,0.2)`

Grades are in `[0, 1]` (1 = perfect); the products fall as degradations appear.

4. Adds **`measure_width`** (double precision) and fills it from
   `public.road_data` rows where `classe = 'Largeur'`, matched on
   `image.id = road_data.image_id` and averaged per image (a few images carry
   several width measurements).
5. Adds **`note_globale`** (numeric) and sets it to
   `LEAST(Note_Structure, Note_Surface)` (after the composite update).

---

## Usage

```bash
python scripts/12_update_notes.py
python scripts/12_update_notes.py --dry-run   # print SQL only
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | YAML config (`source:` block) |
| `--dry-run` | off | Print the SQL and exit without changes |

Runs in a single transaction.

---

## Verified result

- 12,378 images updated; `Note_Structure` / `Note_Surface` / `note_globale`
  populated for all.
- `Note_Structure` re-derived independently from the columns matches the stored
  value exactly (spot-checked); both composites fall in `(0, 1]`.
- `note_globale = LEAST(Note_Structure, Note_Surface)` for **all** rows (0
  mismatches).
- `measure_width` set on 11,136 images; images with no `Largeur` row stay
  `NULL`.

---

## Notes / assumptions

- `referenceGrades` is `jsonb`, so `->>` extracts grade text directly.
- Images without a grade row default to 1.0 (consistent with the task's
  "null ⇒ 1.0" rule). Change the `LEFT JOIN` to an inner join if such images
  should instead be left `NULL`.

## Related files

- `fromrcweb.image_grade` — source grades (`referenceGrades` jsonb).
- `config/config.yaml` — DB connection.
