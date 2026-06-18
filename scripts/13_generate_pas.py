"""Step 1.3 — generate fixed-step road segments (``pas``) from troncon_client.

For the part of ``client.troncon_client`` that lies on an itinerary
(``client.itineraires_v2``), this builds ``client.pas_50`` (50 m steps) and
``client.pas_100`` (100 m steps).

Each output row is a fixed-length slice of one troncon:

- **Intersecting part** — a troncon is kept only where its own vertices lie
  within ``--tol`` metres of the (re-projected) itinerary line; the covered
  cumul (M) range ``[a0, a1]`` is the min/max M of those vertices. (Using the
  troncon's own vertices keeps the M measure, which ``ST_Intersection`` drops.)
- **cumuld / cumulf** — stepped from ``a0`` by the step size; the last slice
  ends at ``a1``. These are LRS cumul (the troncon ``geom`` M values).
- **geom** — ``ST_LocateBetween(troncon.geom, cumuld, cumulf)`` →
  ``LineStringM, 2154`` (the road line of the slice).
- **avg_width** — average non-null ``public.image.measure_width`` of the images
  on that troncon within ``[cumuld, cumulf]``; falls back to a fixed *largeur*
  (5.5 m, or 7 m for the structural network RD806/RD809).
- **id_tronc, axe, nb_pl_final, nature_cr_final** — carried from the troncon.

Usage
-----
    python scripts/13_generate_pas.py
    python scripts/13_generate_pas.py --tol 15 --dry-run
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
TARGET_SRID = 2154
LARGEUR_DEFAULT = 5.5
LARGEUR_STRUCTURAL = 7.0
# Axe codes of the "réseau structurant" (7 m wide). RD806/RD809 in any of the
# encodings seen in the data.
STRUCTURAL_AXES = ("RD806", "RD809", "078D0806", "078D0809")


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


def build_create(out: sql.Composed, step: float, tol: float) -> sql.Composed:
    largeur = sql.SQL(
        "CASE WHEN s.axe IN ({axes}) THEN {struct} ELSE {default} END"
    ).format(
        axes=sql.SQL(", ").join(sql.Literal(a) for a in STRUCTURAL_AXES),
        struct=sql.Literal(LARGEUR_STRUCTURAL), default=sql.Literal(LARGEUR_DEFAULT))

    def avg_note(col: str) -> sql.Composed:
        """Average of a non-null image note over the step's images; 1.0 fallback."""
        c = sql.Identifier(col)
        return sql.SQL(
            "COALESCE((SELECT avg(im.{c}) FROM public.image im "
            "WHERE im.id_tronc = s.id_tronc AND im.{c} IS NOT NULL "
            "AND im.cumuld BETWEEN s.cumuld AND s.cumulf), 1.0)::numeric"
        ).format(c=c)

    return sql.SQL(
        """
        CREATE TABLE {out} AS
        WITH iti AS (
            SELECT axe, ST_Transform(ST_Collect(geom), {srid}) AS g
            FROM client.itineraires_v2 GROUP BY axe
        ),
        rng AS (
            SELECT t.id_tronc, t.axe, t.geom, t.nb_pl_final, t.nature_cr_final,
                   (SELECT min(ST_M(dp.geom)) FROM ST_DumpPoints(t.geom) dp
                     WHERE ST_DWithin(dp.geom, i.g, %(tol)s)) AS a0,
                   (SELECT max(ST_M(dp.geom)) FROM ST_DumpPoints(t.geom) dp
                     WHERE ST_DWithin(dp.geom, i.g, %(tol)s)) AS a1
            FROM client.troncon_client t
            JOIN iti i ON i.axe = t.axe
        ),
        steps AS (
            SELECT r.id_tronc, r.axe, r.geom, r.nb_pl_final, r.nature_cr_final,
                   round(r.a0 + gs * %(step)s)::bigint AS cumuld,
                   round(least(r.a0 + (gs + 1) * %(step)s, r.a1))::bigint AS cumulf
            FROM rng r,
                 generate_series(0, ceil((r.a1 - r.a0) / %(step)s)::int - 1) gs
            WHERE r.a0 IS NOT NULL AND r.a1 > r.a0
        ),
        segll AS (
            SELECT s.id_tronc, s.axe, s.cumuld, s.cumulf, s.nb_pl_final,
                   s.nature_cr_final,
                   ST_GeometryN(ST_LocateBetween(s.geom, s.cumuld, s.cumulf), 1)
                       ::geometry(LineStringM, {srid}) AS geom_line,
                   COALESCE(
                       (SELECT avg(im.measure_width) FROM public.image im
                         WHERE im.id_tronc = s.id_tronc
                           AND im.measure_width IS NOT NULL
                           AND im.cumuld BETWEEN s.cumuld AND s.cumulf),
                       {largeur})::numeric AS avg_width,
                   {avg_global}  AS avg_note_global,
                   {avg_struct}  AS avg_note_structure,
                   {avg_surface} AS avg_note_surface
            FROM steps s
            WHERE s.cumulf > s.cumuld
        )
        SELECT row_number() OVER (ORDER BY id_tronc, cumuld) AS id,
               id_tronc, axe, cumuld, cumulf, avg_width,
               (cumulf - cumuld) * COALESCE(avg_width, 5.5) AS surface,
               avg_note_global, avg_note_structure, avg_note_surface,
               nb_pl_final, nature_cr_final,
               geom_line AS geom
        FROM segll
        WHERE geom_line IS NOT NULL
        """
    ).format(out=out, srid=sql.Literal(TARGET_SRID), largeur=largeur,
             avg_global=avg_note("Note_Global"),
             avg_struct=avg_note("Note_Structure"),
             avg_surface=avg_note("Note_Surface"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--tol", type=float, default=15.0,
                        help="Distance (m) for a troncon vertex to count as on "
                             "the itinerary (default 15).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and exit without changes.")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    targets = [(50.0, "pas_50"), (100.0, "pas_100")]

    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    conn = connect(cfg)
    conn.autocommit = False
    try:
        for step, table in targets:
            out = sql.SQL("client.{}").format(sql.Identifier(table))
            drop = sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(out)
            create = build_create(out, step, args.tol)
            add_pk = sql.SQL("ALTER TABLE {} ADD PRIMARY KEY (id)").format(out)
            if args.dry_run:
                with conn.cursor() as cur:
                    print(f"\n-- {table} (step {step:.0f} m) --", file=sys.stderr)
                    print(drop.as_string(cur) + ";", file=sys.stderr)
                    print(create.as_string(cur) + ";", file=sys.stderr)
                    print(add_pk.as_string(cur) + ";", file=sys.stderr)
                continue
            with conn.cursor() as cur:
                cur.execute(drop)
                cur.execute(create, {"tol": args.tol, "step": step})
                cur.execute(add_pk)
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(out))
                n = cur.fetchone()[0]
            print(f"  client.{table}: {n} segments", file=sys.stderr)
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
