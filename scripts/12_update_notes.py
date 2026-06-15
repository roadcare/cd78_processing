"""Step 1.2 — populate degradation notes on ``public.image``.

Adds 26 ``"Note_<DEGRADATION>"`` numeric columns, fills them from
``fromrcweb.image_grade."referenceGrades"`` (jsonb), then adds and computes
``Note_Structure`` and ``Note_Surface``.

Rules
-----
- Match ``image.id = image_grade."imageId"::uuid``.
- ``"Note_<X>" = COALESCE((referenceGrades ->> '<X>')::numeric, 1.0)`` — an
  absent key, an empty ``{}``, a null ``referenceGrades`` *or* an image with no
  grade row all default to **1.0** (perfect / no degradation). A ``LEFT JOIN``
  with ``COALESCE`` covers every case in one pass.
- ``Note_Structure`` and ``Note_Surface`` are the product of
  ``power(Note_x, exponent)`` over the columns/exponents below (the task's
  ``**`` is SQL ``power()``).

Usage
-----
    python scripts/12_update_notes.py
    python scripts/12_update_notes.py --dry-run
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

# The 26 degradation note columns (suffix = the referenceGrades key).
NOTE_COLS = [
    "Note_AFFAISSEMENT_SIGNIFICATIF",
    "Note_AFFAISSEMENT_GRAVE",
    "Note_ARRACHEMENT_SURFACE",
    "Note_ARRACHEMENT_PROFOND",
    "Note_AUTRE",
    "Note_JOINT_LONGITUDINAL",
    "Note_JOINT_TRANSVERSAL",
    "Note_NID_DE_POULE",
    "Note_ORNIERAGE_SIGNIFICATIF",
    "Note_ORNIERAGE_GRAVE",
    "Note_REGARD",
    "Note_TAMPON",
    "Note_FAIENCAGE_SIGNIFICATIF",
    "Note_FAIENCAGE_GRAVE",
    "Note_FAIENCAGE_BDR",
    "Note_FISSURE_LONGITUDINALE_SIGNIFICATIVE",
    "Note_FISSURE_LONGITUDINALE_GRAVE",
    "Note_FISSURE_LONGITUDINALE_BDR",
    "Note_FISSURE_LONGITUDINALE_PONTEE",
    "Note_FISSURE_TRANSVERSALE_SIGNIFICATIVE",
    "Note_FISSURE_TRANSVERSALE_GRAVE",
    "Note_FISSURE_TRANSVERSALE_PONTEE",
    "Note_GLACAGE_RESSUAGE_LOCALISE",
    "Note_GLACAGE_RESSUAGE_GENERALISE",
    "Note_REPARATION_PETITE_LARGEUR",
    "Note_REPARATION_PLEINE_LARGEUR",
]

# (column, exponent) factors for the two composite notes.
STRUCTURE = [
    ("Note_AFFAISSEMENT_SIGNIFICATIF", 0.8),
    ("Note_AFFAISSEMENT_GRAVE", 1.0),
    ("Note_ORNIERAGE_SIGNIFICATIF", 0.8),
    ("Note_ORNIERAGE_GRAVE", 1.0),
    ("Note_FAIENCAGE_SIGNIFICATIF", 1.0),
    ("Note_FAIENCAGE_GRAVE", 1.0),
    ("Note_FAIENCAGE_BDR", 1.0),
    ("Note_FISSURE_LONGITUDINALE_GRAVE", 1.0),
    ("Note_FISSURE_LONGITUDINALE_BDR", 1.0),
    ("Note_FISSURE_LONGITUDINALE_PONTEE", 0.1),
    ("Note_FISSURE_TRANSVERSALE_GRAVE", 1.0),
    ("Note_FISSURE_TRANSVERSALE_PONTEE", 0.1),
    ("Note_REPARATION_PETITE_LARGEUR", 0.1),
    ("Note_REPARATION_PLEINE_LARGEUR", 0.1),
]
SURFACE = [
    ("Note_ARRACHEMENT_SURFACE", 0.1),
    ("Note_ARRACHEMENT_PROFOND", 0.5),
    ("Note_JOINT_LONGITUDINAL", 0.1),
    ("Note_JOINT_TRANSVERSAL", 0.1),
    ("Note_NID_DE_POULE", 1.0),
    ("Note_FAIENCAGE_SIGNIFICATIF", 1.0),
    ("Note_FAIENCAGE_GRAVE", 1.0),
    ("Note_FAIENCAGE_BDR", 1.0),
    ("Note_FISSURE_LONGITUDINALE_SIGNIFICATIVE", 0.8),
    ("Note_FISSURE_LONGITUDINALE_GRAVE", 1.0),
    ("Note_FISSURE_LONGITUDINALE_BDR", 1.0),
    ("Note_FISSURE_TRANSVERSALE_SIGNIFICATIVE", 0.8),
    ("Note_GLACAGE_RESSUAGE_LOCALISE", 0.1),
    ("Note_GLACAGE_RESSUAGE_GENERALISE", 0.1),
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


def build_statements() -> dict[str, list[sql.Composed] | sql.Composed]:
    img = sql.SQL("public.image")
    grade = sql.SQL("fromrcweb.image_grade")

    add_notes = [
        sql.SQL("ALTER TABLE {img} ADD COLUMN IF NOT EXISTS {c} numeric").format(
            img=img, c=sql.Identifier(col))
        for col in NOTE_COLS
    ]

    set_items = [
        sql.SQL("{c} = COALESCE((s.rg ->> {k})::numeric, 1.0)").format(
            c=sql.Identifier(col), k=sql.Literal(col[len("Note_"):]))
        for col in NOTE_COLS
    ]
    update_notes = sql.SQL(
        """
        UPDATE {img} t1 SET
            {sets}
        FROM (
            SELECT i.id, g."referenceGrades" AS rg
            FROM {img} i
            LEFT JOIN {grade} g ON i.id = g."imageId"::uuid
        ) s
        WHERE t1.id = s.id
        """
    ).format(img=img, grade=grade, sets=sql.SQL(",\n            ").join(set_items))

    add_composite = [
        sql.SQL("ALTER TABLE {img} ADD COLUMN IF NOT EXISTS {c} numeric").format(
            img=img, c=sql.Identifier(c)) for c in ("Note_Structure", "Note_Surface")
    ]

    def product(factors: list[tuple[str, float]]) -> sql.Composed:
        return sql.SQL(" * ").join(
            sql.SQL("power({c}, {e})").format(
                c=sql.Identifier(col), e=sql.Literal(exp))
            for col, exp in factors)

    update_composite = sql.SQL(
        "UPDATE {img} SET {st} = {sexpr}, {su} = {uexpr}"
    ).format(img=img,
             st=sql.Identifier("Note_Structure"), sexpr=product(STRUCTURE),
             su=sql.Identifier("Note_Surface"), uexpr=product(SURFACE))

    return {"add_notes": add_notes, "update_notes": update_notes,
            "add_composite": add_composite, "update_composite": update_composite}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and exit without changes.")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    stmts = build_statements()

    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    conn = connect(cfg)
    conn.autocommit = False
    try:
        if args.dry_run:
            with conn.cursor() as cur:
                for s in stmts["add_notes"]:
                    print(s.as_string(cur) + ";", file=sys.stderr)
                print("\n" + stmts["update_notes"].as_string(cur) + ";",
                      file=sys.stderr)
                for s in stmts["add_composite"]:
                    print("\n" + s.as_string(cur) + ";", file=sys.stderr)
                print("\n" + stmts["update_composite"].as_string(cur) + ";",
                      file=sys.stderr)
            conn.rollback()
            return 0

        with conn.cursor() as cur:
            for s in stmts["add_notes"]:
                cur.execute(s)
            cur.execute(stmts["update_notes"])
            n_notes = cur.rowcount
            for s in stmts["add_composite"]:
                cur.execute(s)
            cur.execute(stmts["update_composite"])
            n_comp = cur.rowcount
        conn.commit()
        print(f"  Note_* columns updated: {n_notes} images", file=sys.stderr)
        print(f"  Note_Structure/Surface: {n_comp} images", file=sys.stderr)
        print("Done.", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
