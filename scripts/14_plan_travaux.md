# `14_plan_travaux.py`

Step 1.4 — *plan_travaux_et_budget*. Applies the decision matrix
(`matrice_decision_rules.md`, extracted from `pas_Antonin.xlsx`) to
`client.pas_50` and `client.pas_100`: adds the decision columns and fills them
for every segment.

## Columns added (per pas table)

| Column | Type | Derived from |
|---|---|---|
| `Note_globale` | integer | `floor(avg_note_global * 20)` (Excel ROUNDDOWN) |
| `Note_structure` | integer | `round(avg_note_structure * 20)` |
| `Note_surface` | integer | `round(avg_note_surface * 20)` |
| `Etat_global` | text | `Note_globale` → A/B/C (info only) |
| `Etat_structure` | text | `Note_structure` → A/B/C |
| `Etat_surface` | text | `Note_surface` → A/B/C |
| `classe_trafic_PL` | text | `nb_pl_final` → T5…T0 |
| `Importance_trafic_PL` | text | traffic class → Faible/Moyen/Important |
| `Type_chaussée` | text | `nature_cr_final` → BB/LH/Souple |
| `code_unique_simple` | text | `<struct>-<surf>-<type>-<importance>` |
| `Priorite` | text | matrix lookup (`-`, P1, P2, P3) |
| `Technique_entretien` | text | matrix lookup |
| `Cout_surfacique` | numeric | matrix lookup (€/m²) |
| `Cout_Total` | numeric | `round(Cout_surfacique * surface, -2)` (nearest €100) |

## How it works

1. **État (3 classes)** for each note `n`: `n<=8 → C-Mauvais`, `8<n<15 →
   B-Moyen`, `n>=15 → A-Bon`. Only `Etat_structure` + `Etat_surface` feed the
   matrix (`Etat_global` is informative).
2. **classe_trafic_PL** from `nb_pl_final`: `<25 T5`, `25–50 T4`, `50–85 T3-`,
   `85–150 T3+`, `150–300 T2`, `300–750 T1`, `>=750 T0`.
3. **Type_chaussée**: BB/BBM/BBTM/BBME/ECF → `BB`; BBSG/BBSG ET ECF/BBSG/BBME →
   `LH`; ESU/ES → `Souple`.
4. **code_unique_simple** = first letter of `Etat_structure` and `Etat_surface`
   + `Type_chaussée` + `Importance_trafic_PL` (e.g. `A-B-BB-Faible`).
5. The 80-row matrix (embedded as a `MATRICE` constant / `VALUES` CTE) is joined
   on `code_unique_simple` → `Priorite`, `Technique_entretien`,
   `Cout_surfacique`. `Cout_Total` is then computed from `surface`.

The whole thing is one `UPDATE` per table after `ADD COLUMN IF NOT EXISTS`, so
the script is **idempotent** — re-running recomputes every row and leaves the
table, PK and `geom` untouched.

## Usage

```bash
python scripts/14_plan_travaux.py            # update pas_50 + pas_100
python scripts/14_plan_travaux.py --dry-run  # print SQL, change nothing
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `config/config.yaml` | YAML config (`source:`) |
| `--dry-run` | off | Print the ALTER + UPDATE SQL and roll back |

## Verified result

- `client.pas_50`: 1527 rows updated, 0 without a matrix match.
- `client.pas_100`: 781 rows updated, 0 without a matrix match.
- Cross-checked all 781 `pas_100` rows against `pas_Antonin.xlsx` (sheet
  `pas_100`): **0 mismatches** across all 13 derived columns + `Cout_Total`.

## Notes

- The matrix is the 3-class (`A/B/C`) version, not the 4-class `_OLD` display
  states. Source of truth: `matrice_decision_rules.md`.
- Any segment whose `nature_cr_final` is outside the `Type_chaussée` table would
  leave `code_unique_simple` / `Priorite` NULL — the run prints the count of
  such rows (0 on current data).

## Related files

- `matrice_decision_rules.md` — the rules this script implements.
- `scripts/13_generate_pas.py` — builds the `pas_50` / `pas_100` tables this
  step enriches.
