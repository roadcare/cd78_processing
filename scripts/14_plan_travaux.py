"""Step 1.4 — plan_travaux_et_budget: apply the decision matrix to the *pas*.

Adds and populates the decision columns on ``client.pas_50`` and
``client.pas_100`` from the rules in ``matrice_decision_rules.md`` (extracted
from ``pas_Antonin.xlsx``).

For each segment the chain is:

1. **Notes 0–20** — ``Note_structure``/``Note_surface = round(avg_note_* * 20)``;
   ``Note_globale = LEAST(Note_structure, Note_surface)``.
2. **État (3 classes)** — for each note ``n``: ``n<=8 → C-Mauvais``,
   ``8<n<16 → B-Moyen``, ``n>=16 → A-Bon``. (``Etat_global`` is informative;
   only structure + surface feed the matrix.)
3. **classe_trafic_PL** from ``nb_pl_final`` (T5…T0).
4. **Importance_trafic_PL** from the traffic class (Faible/Moyen/Important).
5. **Type_chaussée** from ``nature_cr_final`` (BB/LH/Souple).
6. **code_unique_simple** = ``<struct>-<surf>-<type>-<importance>`` (first letter
   of each état).
7. **Matrix lookup** (``MATRICE`` below, 81 rows) → ``Priorite``,
   ``Technique_entretien``, ``Cout_surfacique``.
8. **Cout_Total** = ``round(Cout_surfacique * surface, -2)`` (nearest €100).

The script is idempotent: columns are added with ``IF NOT EXISTS`` and every row
is re-computed with a single ``UPDATE`` per table (table, PK and geom untouched).

Usage
-----
    python scripts/14_plan_travaux.py
    python scripts/14_plan_travaux.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Decision matrix (matrice_decision_rules.md): code_unique_simple ->
# (Priorite, Technique_entretien, Cout_surfacique €/m²).
MATRICE: list[tuple[str, str, str, int]] = [
    ('A-A-BB-Faible', '-', 'RAS', 0),
    ('A-A-BB-Important', '-', 'RAS', 0),
    ('A-A-BB-Moyen', '-', 'RAS', 0),
    ('A-A-LH-Faible', '-', 'RAS', 0),
    ('A-A-LH-Important', '-', 'RAS', 0),
    ('A-A-LH-Moyen', '-', 'RAS', 0),
    ('A-A-Souple-Faible', '-', 'RAS', 0),
    ('A-A-Souple-Important', '-', 'RAS', 0),
    ('A-A-Souple-Moyen', '-', 'RAS', 0),
    ('A-B-BB-Faible', 'P2', 'ECF/ESU', 15),
    ('A-B-BB-Important', 'P1', 'BBM', 27),
    ('A-B-BB-Moyen', 'P1', 'ECF/ESU', 15),
    ('A-B-LH-Faible', 'P2', 'ECF/ESU', 15),
    ('A-B-LH-Important', 'P1', 'BBSG', 28),
    ('A-B-LH-Moyen', 'P1', 'BBSG', 28),
    ('A-B-Souple-Faible', 'P2', 'ECF/ESU', 15),
    ('A-B-Souple-Important', 'P1', 'ECF/ESU', 15),
    ('A-B-Souple-Moyen', 'P1', 'ECF/ESU', 15),
    ('A-C-BB-Faible', 'P1', 'ECF/ESU', 15),
    ('A-C-BB-Important', 'P1', 'BBM', 27),
    ('A-C-BB-Moyen', 'P1', 'ECF/ESU', 15),
    ('A-C-LH-Faible', 'P1', 'ECF/ESU', 15),
    ('A-C-LH-Important', 'P1', 'BBSG', 28),
    ('A-C-LH-Moyen', 'P1', 'BBSG', 28),
    ('A-C-Souple-Faible', 'P1', 'ECF/ESU', 15),
    ('A-C-Souple-Important', 'P1', 'ECF/ESU', 15),
    ('A-C-Souple-Moyen', 'P1', 'ECF/ESU', 15),
    ('B-A-BB-Faible', 'P3', 'BBM', 27),
    ('B-A-BB-Important', 'P1', 'BBM', 27),
    ('B-A-BB-Moyen', 'P2', 'BBM', 27),
    ('B-A-LH-Faible', 'P3', 'ECF/ESU', 15),
    ('B-A-LH-Important', 'P1', 'BBSG', 28),
    ('B-A-LH-Moyen', 'P1', 'Traitement de surface + BBSG', 43),
    ('B-A-Souple-Faible', 'P3', 'BBM', 27),
    ('B-A-Souple-Important', 'P1', 'BBM', 27),
    ('B-A-Souple-Moyen', 'P2', 'BBM', 27),
    ('B-B-BB-Faible', 'P2', 'BBM', 27),
    ('B-B-BB-Important', 'P1', 'BBM', 27),
    ('B-B-BB-Moyen', 'P1', 'BBM', 27),
    ('B-B-LH-Faible', 'P2', 'Traitement de surface + BBSG', 43),
    ('B-B-LH-Important', 'P1', 'GB+BBM', 75),
    ('B-B-LH-Moyen', 'P1', 'Traitement de surface + BBSG', 43),
    ('B-B-Souple-Faible', 'P2', 'BBM', 27),
    ('B-B-Souple-Important', 'P1', 'BBM', 27),
    ('B-B-Souple-Moyen', 'P1', 'BBM', 27),
    ('B-C-BB-Faible', 'P2', 'BBM', 27),
    ('B-C-BB-Important', 'P1', 'BBM', 27),
    ('B-C-BB-Moyen', 'P2', 'BBM', 27),
    ('B-C-LH-Faible', 'P2', 'Traitement de surface + BBSG', 43),
    ('B-C-LH-Important', 'P1', 'GB+BBM', 75),
    ('B-C-LH-Moyen', 'P2', 'Traitement de surface + BBSG', 43),
    ('B-C-Souple-Faible', 'P2', 'BBM', 27),
    ('B-C-Souple-Important', 'P1', 'BBM', 27),
    ('B-C-Souple-Moyen', 'P2', 'BBM', 27),
    ('C-A-BB-Faible', 'P3', 'BBM', 27),
    ('C-A-BB-Important', 'P1', 'GB+BBM', 75),
    ('C-A-BB-Moyen', 'P2', 'BBM', 27),
    ('C-A-LH-Faible', 'P3', 'Traitement de surface + BBSG', 43),
    ('C-A-LH-Important', 'P1', 'GB + BBM', 75),
    ('C-A-LH-Moyen', 'P2', 'GB+BBM', 75),
    ('C-A-Souple-Faible', 'P3', 'Traitement de surface + ECF/ESU', 30),
    ('C-A-Souple-Important', 'P1', 'Traitement de surface + BBM', 42),
    ('C-A-Souple-Moyen', 'P2', 'Traitement de surface + BBM', 42),
    ('C-B-BB-Faible', 'P3', 'BBM', 27),
    ('C-B-BB-Important', 'P1', 'GB+BBM', 75),
    ('C-B-BB-Moyen', 'P2', 'BBM', 27),
    ('C-B-LH-Faible', 'P3', 'Traitement de surface + BBSG', 43),
    ('C-B-LH-Important', 'P1', 'GB + BBM', 75),
    ('C-B-LH-Moyen', 'P2', 'GB+BBM', 75),
    ('C-B-Souple-Faible', 'P3', 'Traitement de surface + ECF/ESU', 30),
    ('C-B-Souple-Important', 'P1', 'Traitement de surface + BBM', 42),
    ('C-B-Souple-Moyen', 'P3', 'Traitement de surface + BBM', 42),
    ('C-C-BB-Faible', 'P3', 'BBM', 27),
    ('C-C-BB-Important', 'P1', 'GB+BBM', 75),
    ('C-C-BB-Moyen', 'P2', 'BBM', 27),
    ('C-C-LH-Faible', 'P3', 'Traitement de surface + BBSG', 43),
    ('C-C-LH-Important', 'P1', 'GB + BBM', 75),
    ('C-C-LH-Moyen', 'P2', 'GB+BBM', 75),
    ('C-C-Souple-Faible', 'P3', 'Traitement de surface + ECF/ESU', 30),
    ('C-C-Souple-Important', 'P1', 'Traitement de surface + BBM', 42),
    ('C-C-Souple-Moyen', 'P3', 'Traitement de surface + BBM', 42),
]

# nature_cr_final -> Type_chaussée
TYPE_CHAUSSEE = {
    "BB": "BB", "BBM": "BB", "BBTM": "BB", "BBME": "BB", "ECF": "BB",
    "BBSG": "LH", "BBSG ET ECF": "LH", "BBSG/BBME": "LH",
    "ESU": "Souple", "ES": "Souple",
}

# New columns to add (name -> SQL type).
NEW_COLUMNS: list[tuple[str, str]] = [
    ("Note_globale", "integer"),
    ("Note_structure", "integer"),
    ("Note_surface", "integer"),
    ("Etat_surface", "text"),
    ("Etat_structure", "text"),
    ("Etat_global", "text"),
    ("classe_trafic_PL", "text"),
    ("Importance_trafic_PL", "text"),
    ("Type_chaussée", "text"),
    ("code_unique_simple", "text"),
    ("Priorite", "text"),
    ("Technique_entretien", "text"),
    ("Cout_surfacique", "numeric"),
    ("Cout_Total", "numeric"),
]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not raw or "source" not in raw:
        raise ValueError(f"Config {path} is missing the 'source' section")
    src = raw["source"]
    for key in ("host", "port", "user", "password", "database"):
        if key not in src:
            raise ValueError(f"Config 'source' is missing key: {key}")
    return src


def connect(cfg: dict[str, Any]):
    return psycopg2.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], dbname=cfg["database"])


def add_columns(out: sql.Composed) -> sql.Composed:
    parts = [
        sql.SQL("ADD COLUMN IF NOT EXISTS {} {}").format(
            sql.Identifier(name), sql.SQL(typ))
        for name, typ in NEW_COLUMNS
    ]
    return sql.SQL("ALTER TABLE {out} {cols}").format(
        out=out, cols=sql.SQL(", ").join(parts))


def matrice_values() -> sql.Composed:
    rows = [
        sql.SQL("({}, {}, {}, {})").format(
            sql.Literal(code), sql.Literal(prio),
            sql.Literal(tech), sql.Literal(cost))
        for code, prio, tech, cost in MATRICE
    ]
    return sql.SQL(", ").join(rows)


def type_chaussee_case() -> sql.Composed:
    whens = [
        sql.SQL("WHEN {} THEN {}").format(sql.Literal(k), sql.Literal(v))
        for k, v in TYPE_CHAUSSEE.items()
    ]
    return sql.SQL("CASE nature_cr_final {whens} ELSE NULL END").format(
        whens=sql.SQL(" ").join(whens))


def build_update(out: sql.Composed) -> sql.Composed:
    """Single UPDATE that derives every decision column for one pas table."""
    return sql.SQL(
        """
        WITH matrice(code, prio, tech, cost) AS (VALUES {matrice}),
        derived AS (
            SELECT id,
                   round(avg_note_structure * 20)::int AS n_struct,
                   round(avg_note_surface   * 20)::int AS n_surf,
                   -- Note_globale = LEAST(Note_structure, Note_surface)
                   LEAST(round(avg_note_structure * 20)::int,
                         round(avg_note_surface   * 20)::int) AS n_glob,
                   {type_chaussee} AS type_ch,
                   CASE WHEN nb_pl_final >= 750 THEN 'T0'
                        WHEN nb_pl_final >= 300 THEN 'T1'
                        WHEN nb_pl_final >= 150 THEN 'T2'
                        WHEN nb_pl_final >= 85  THEN 'T3+'
                        WHEN nb_pl_final >= 50  THEN 'T3-'
                        WHEN nb_pl_final >= 25  THEN 'T4'
                        ELSE 'T5' END AS trafic
            FROM {out}
        ),
        keyed AS (
            SELECT d.*,
                   CASE WHEN n_glob   <= 8 THEN 'C-Mauvais'
                        WHEN n_glob   >= 16 THEN 'A-Bon' ELSE 'B-Moyen' END AS etat_glob,
                   CASE WHEN n_struct <= 8 THEN 'C-Mauvais'
                        WHEN n_struct >= 16 THEN 'A-Bon' ELSE 'B-Moyen' END AS etat_struct,
                   CASE WHEN n_surf   <= 8 THEN 'C-Mauvais'
                        WHEN n_surf   >= 16 THEN 'A-Bon' ELSE 'B-Moyen' END AS etat_surf,
                   CASE WHEN trafic IN ('T1','T0') THEN 'Important'
                        WHEN trafic IN ('T3+','T2') THEN 'Moyen'
                        ELSE 'Faible' END AS importance
            FROM derived d
        ),
        code AS (
            SELECT k.*,
                   left(etat_struct,1) || '-' || left(etat_surf,1) || '-'
                       || type_ch || '-' || importance AS code_unique
            FROM keyed k
        )
        UPDATE {out} p SET
            "Note_globale"         = c.n_glob,
            "Note_structure"       = c.n_struct,
            "Note_surface"         = c.n_surf,
            "Etat_global"          = c.etat_glob,
            "Etat_structure"       = c.etat_struct,
            "Etat_surface"         = c.etat_surf,
            "classe_trafic_PL"     = c.trafic,
            "Importance_trafic_PL" = c.importance,
            "Type_chaussée"        = c.type_ch,
            "code_unique_simple"   = c.code_unique,
            "Priorite"             = m.prio,
            "Technique_entretien"  = m.tech,
            "Cout_surfacique"      = m.cost,
            "Cout_Total"           = round((m.cost * p.surface) / 100.0) * 100
        FROM code c
        LEFT JOIN matrice m ON m.code = c.code_unique
        WHERE p.id = c.id
        """
    ).format(out=out, matrice=matrice_values(),
             type_chaussee=type_chaussee_case())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and exit without changes.")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    tables = ["pas_50", "pas_100"]

    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    conn = connect(cfg)
    conn.autocommit = False
    try:
        for table in tables:
            out = sql.SQL("client.{}").format(sql.Identifier(table))
            alter = add_columns(out)
            update = build_update(out)
            if args.dry_run:
                with conn.cursor() as cur:
                    print(f"\n-- {table} --", file=sys.stderr)
                    print(alter.as_string(cur) + ";", file=sys.stderr)
                    print(update.as_string(cur) + ";", file=sys.stderr)
                continue
            with conn.cursor() as cur:
                cur.execute(alter)
                cur.execute(update)
                n = cur.rowcount
                cur.execute(sql.SQL(
                    'SELECT COUNT(*) FROM {} WHERE "Priorite" IS NULL').format(out))
                unmatched = cur.fetchone()[0]
            print(f"  client.{table}: {n} rows updated"
                  f" ({unmatched} without a matrix match)", file=sys.stderr)
        if args.dry_run:
            conn.rollback()
            return 0
        conn.commit()
        print("Done.", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
