"""Build ``client.troncon_client`` from the step-0.4 overlay table.

Takes the finest-overlay table (default
``client."20260301_trafic_couche_roulement_intersection"``) and, for every row:

1. **Fuse** the geometry with ``ST_LineMerge`` (MultiLineString → LineString
   when the parts are contiguous).
2. **Decompose** the result into individual LineStrings (``ST_Dump``). For each
   piece, ``cumuld`` / ``cumulf`` are split **proportionally by length** (in
   component order); the PR references are updated so the first piece keeps the
   row's ``plod`` / ``absd``, the last keeps ``plof`` / ``absf``, and interior
   boundary abscissae are interpolated linearly by cumul (``plo`` carries
   ``plod`` — approximate where a piece crosses a PR reset). Single-piece rows
   are unchanged.
3. **Write** to the output table with a new ``id_tronc`` primary key. ``geom``
   becomes ``geometry(LineStringM, <srid>)`` (default 2154), built with
   ``ST_AddMeasure(geom, cumuld, cumulf)`` after ``ST_Transform`` to the target
   SRID when the source SRID differs.

All other source columns (axe, the value columns, ``_final`` columns, the
original ``id``, …) are carried over unchanged. Two derived columns are added:
``len_shp`` (``ST_Length(geom)``) and ``len_cumul`` (``abs(cumulf-cumuld)``).

4. **Correct PR references** so successive segments of an axe agree at their
   shared boundary (``t2.cumuld = t1.cumulf`` ⇒ ``t2.plod/absd = t1.plof/absf``).
   Where they disagree, the side whose PR position ``plo*1000 + abs`` is closest
   to the cumul wins and is copied to the other side.

Usage
-----
    python scripts/05_build_troncon.py
    python scripts/05_build_troncon.py \\
        --source client.20260301_trafic_couche_roulement_intersection \\
        --output client.troncon_client --target-srid 2154 --dry-run
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
DEFAULT_SOURCE = "client.20260301_trafic_couche_roulement_intersection"
DEFAULT_OUTPUT = "client.troncon_client"


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


def parse_qualified(name: str) -> tuple[str, str]:
    parts = name.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected 'schema.table', got: {name!r}")
    return parts[0], parts[1]


def fetch_columns(cur, schema: str, table: str) -> list[str]:
    cur.execute(
        """
        SELECT a.attname FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def fetch_srid(cur, schema: str, table: str, geom_col: str) -> int:
    cur.execute(
        sql.SQL("SELECT ST_SRID({g}) FROM {s}.{t} WHERE {g} IS NOT NULL LIMIT 1")
        .format(g=sql.Identifier(geom_col),
                s=sql.Identifier(schema), t=sql.Identifier(table)))
    row = cur.fetchone()
    return row[0] if row else 0


def build_select(
    src: sql.Composed, columns: list[str], src_srid: int, target_srid: int,
    geom_col: str, cumuld_col: str, cumulf_col: str,
    plod_col: str, absd_col: str, plof_col: str, absf_col: str, id_col: str,
) -> sql.Composed:
    GEOM = sql.Identifier(geom_col)
    CD, CF = sql.Identifier(cumuld_col), sql.Identifier(cumulf_col)
    PLOD, ABSD = sql.Identifier(plod_col), sql.Identifier(absd_col)
    PLOF, ABSF = sql.Identifier(plof_col), sql.Identifier(absf_col)
    IDP = sql.Identifier(id_col)

    # Fraction of the full cumul span at a (rounded) sub-position, 0 when the
    # span is degenerate.
    def absint(pos: sql.Composed) -> sql.Composed:
        return sql.SQL(
            "ROUND({ABSD} + COALESCE(({pos} - {CD})::numeric "
            "/ NULLIF({CF} - {CD}, 0), 0) * ({ABSF} - {ABSD}))::bigint"
        ).format(ABSD=ABSD, ABSF=ABSF, CD=CD, CF=CF, pos=pos)

    # Transformed piece geometry (only transform if SRID differs).
    if src_srid != target_srid:
        tgeom = sql.SQL("ST_Transform(pgeom, {srid})").format(
            srid=sql.Literal(target_srid))
    else:
        tgeom = sql.SQL("pgeom")
    geom_expr = sql.SQL(
        "ST_AddMeasure({tg}, _cd, _cf)::geometry(LineStringM, {srid})"
    ).format(tg=tgeom, srid=sql.Literal(target_srid))

    # Output columns: id_tronc first, then every source column (cumul / PR /
    # geom replaced by the recomputed expressions).
    items = [sql.SQL("row_number() OVER (ORDER BY {IDP}, pn) AS id_tronc")
             .format(IDP=IDP)]
    for c in columns:
        if c == geom_col:
            items.append(sql.SQL("{e} AS {c}").format(e=geom_expr, c=GEOM))
        elif c == cumuld_col:
            items.append(sql.SQL("_cd AS {c}").format(c=CD))
        elif c == cumulf_col:
            items.append(sql.SQL("_cf AS {c}").format(c=CF))
        elif c == absd_col:
            items.append(sql.SQL("_absd AS {c}").format(c=ABSD))
        elif c == absf_col:
            items.append(sql.SQL("_absf AS {c}").format(c=ABSF))
        elif c == plof_col:
            items.append(sql.SQL("_plof AS {c}").format(c=PLOF))
        else:  # plod and all carried columns unchanged
            items.append(sql.Identifier(c))
    # Derived length columns.
    items.append(sql.SQL("ST_Length({tg})::numeric AS len_shp").format(tg=tgeom))
    items.append(sql.SQL("abs(_cf - _cd) AS len_cumul"))
    select_items = sql.SQL(",\n               ").join(items)

    return sql.SQL(
        """
        WITH dumped AS (
            SELECT s.*, p.path[1] AS pn, p.geom AS pgeom,
                   ST_Length(p.geom) AS plen
            FROM {src} s
            CROSS JOIN LATERAL ST_Dump(ST_LineMerge(s.{GEOM})) p
        ),
        calc AS (
            SELECT d.*,
                   SUM(plen) OVER (PARTITION BY {IDP}) AS tot,
                   COALESCE(SUM(plen) OVER (PARTITION BY {IDP} ORDER BY pn
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
                            AS off0,
                   COUNT(*) OVER (PARTITION BY {IDP}) AS np
            FROM dumped d
        ),
        geo AS (
            SELECT c.*,
                   ROUND({CD} + COALESCE(off0 / NULLIF(tot, 0), 0)
                         * ({CF} - {CD}))::bigint AS _cd,
                   ROUND({CD} + COALESCE((off0 + plen) / NULLIF(tot, 0), 0)
                         * ({CF} - {CD}))::bigint AS _cf
            FROM calc c
        ),
        geo2 AS (
            SELECT g.*,
                   {absd_expr} AS _absd,
                   {absf_expr} AS _absf,
                   CASE WHEN pn = np THEN {PLOF} ELSE {PLOD} END AS _plof
            FROM geo g
        )
        SELECT {select_items}
        FROM geo2
        """
    ).format(src=src, GEOM=GEOM, IDP=IDP, CD=CD, CF=CF, PLOD=PLOD, PLOF=PLOF,
             absd_expr=absint(sql.SQL("_cd")),
             absf_expr=absint(sql.SQL("_cf")),
             select_items=select_items)


def build_correct_pr(
    out: sql.Composed, axe_col: str, cumuld_col: str, cumulf_col: str,
    plod_col: str, absd_col: str, plof_col: str, absf_col: str,
) -> list[sql.Composed]:
    """Correct the PR references so successive segments of an axe agree at their
    shared boundary (``t2.cumuld = t1.cumulf`` ⇒ ``t2.plod/absd`` should equal
    ``t1.plof/absf``).

    At each mismatched boundary the side whose PR position ``plo*1000 + abs`` is
    closest to the cumul wins and is copied to the other side. The decision is
    materialised first (temp table) so both conditional updates use the original
    values.
    """
    A = sql.Identifier(axe_col)
    CD, CF = sql.Identifier(cumuld_col), sql.Identifier(cumulf_col)
    PLOD, ABSD = sql.Identifier(plod_col), sql.Identifier(absd_col)
    PLOF, ABSF = sql.Identifier(plof_col), sql.Identifier(absf_col)

    def numcast(col: sql.Composed) -> sql.Composed:
        # plod/plof are text kilometric points; treat non-numeric as 0.
        return sql.SQL("(CASE WHEN {c} ~ '^-?[0-9]+$' THEN {c}::numeric ELSE 0 END)"
                       ).format(c=col)

    make = sql.SQL(
        """
        CREATE TEMP TABLE pr_fix ON COMMIT DROP AS
        WITH base AS (
            SELECT id_tronc AS t2_id,
                   {CD} AS cumuld, {PLOD} AS t2_plod, {ABSD} AS t2_absd,
                   LAG(id_tronc) OVER w AS t1_id,
                   LAG({CF})    OVER w AS t1_cumulf,
                   LAG({PLOF})  OVER w AS t1_plof,
                   LAG({ABSF})  OVER w AS t1_absf
            FROM {out}
            WINDOW w AS (PARTITION BY {A} ORDER BY {CD}, {CF}, id_tronc)
        )
        SELECT *,
               abs(t1_cumulf - ({n_t1plof} * 1000.0 + t1_absf)) AS err1,
               abs(cumuld     - ({n_t2plod} * 1000.0 + t2_absd)) AS err2
        FROM base
        WHERE t1_id IS NOT NULL AND t1_cumulf = cumuld
          AND (t2_plod IS DISTINCT FROM t1_plof OR t2_absd IS DISTINCT FROM t1_absf)
        """
    ).format(out=out, A=A, CD=CD, CF=CF, PLOD=PLOD, ABSD=ABSD, PLOF=PLOF,
             ABSF=ABSF, n_t1plof=numcast(sql.SQL("t1_plof")),
             n_t2plod=numcast(sql.SQL("t2_plod")))

    fix_t2 = sql.SQL(
        "UPDATE {out} o SET {PLOD} = f.t1_plof, {ABSD} = f.t1_absf "
        "FROM pr_fix f WHERE o.id_tronc = f.t2_id AND f.err1 <= f.err2"
    ).format(out=out, PLOD=PLOD, ABSD=ABSD)
    fix_t1 = sql.SQL(
        "UPDATE {out} o SET {PLOF} = f.t2_plod, {ABSF} = f.t2_absd "
        "FROM pr_fix f WHERE o.id_tronc = f.t1_id AND f.err1 > f.err2"
    ).format(out=out, PLOF=PLOF, ABSF=ABSF)
    return [make, fix_t2, fix_t1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help=f"Source 'schema.table' (default {DEFAULT_SOURCE}).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output 'schema.table' (default {DEFAULT_OUTPUT}).")
    parser.add_argument("--target-srid", type=int, default=2154)
    parser.add_argument("--axe-col", default="axe")
    parser.add_argument("--geom-col", default="geom")
    parser.add_argument("--cumuld-col", default="cumuld")
    parser.add_argument("--cumulf-col", default="cumulf")
    parser.add_argument("--plod-col", default="plod")
    parser.add_argument("--absd-col", default="absd")
    parser.add_argument("--plof-col", default="plof")
    parser.add_argument("--absf-col", default="absf")
    parser.add_argument("--id-col", default="id",
                        help="Source identifier column (groups a row's pieces).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and exit without changes.")
    args = parser.parse_args(argv)

    src_schema, src_table = parse_qualified(args.source)
    out_schema, out_table = parse_qualified(args.output)
    src_ident = sql.SQL("{}.{}").format(
        sql.Identifier(src_schema), sql.Identifier(src_table))
    out_ident = sql.SQL("{}.{}").format(
        sql.Identifier(out_schema), sql.Identifier(out_table))

    cfg = load_config(args.config)
    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    conn = connect(cfg)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            columns = fetch_columns(cur, src_schema, src_table)
            src_srid = fetch_srid(cur, src_schema, src_table, args.geom_col)
        print(f"Source: {args.source} (SRID {src_srid}) -> {args.output} "
              f"(LineStringM {args.target_srid})", file=sys.stderr)

        select = build_select(
            src_ident, columns, src_srid, args.target_srid, args.geom_col,
            args.cumuld_col, args.cumulf_col, args.plod_col, args.absd_col,
            args.plof_col, args.absf_col, args.id_col)
        drop = sql.SQL("DROP TABLE IF EXISTS {out} CASCADE").format(out=out_ident)
        create = sql.SQL("CREATE TABLE {out} AS {select}").format(
            out=out_ident, select=select)
        set_type = sql.SQL(
            "ALTER TABLE {out} ALTER COLUMN {g} TYPE geometry(LineStringM, {srid}) "
            "USING {g}::geometry(LineStringM, {srid})"
        ).format(out=out_ident, g=sql.Identifier(args.geom_col),
                 srid=sql.Literal(args.target_srid))
        add_pk = sql.SQL("ALTER TABLE {out} ADD PRIMARY KEY (id_tronc)").format(
            out=out_ident)
        correct = build_correct_pr(
            out_ident, args.axe_col, args.cumuld_col, args.cumulf_col,
            args.plod_col, args.absd_col, args.plof_col, args.absf_col)

        if args.dry_run:
            with conn.cursor() as cur:
                for s in (drop, create, set_type, add_pk, *correct):
                    print("\n" + s.as_string(cur) + ";", file=sys.stderr)
            conn.rollback()
            return 0

        with conn.cursor() as cur:
            cur.execute(drop)
            cur.execute(create)
            cur.execute(set_type)
            cur.execute(add_pk)
            # PR boundary correction (materialise decisions, then apply).
            cur.execute(correct[0])
            cur.execute(correct[1])
            n_fix2 = cur.rowcount
            cur.execute(correct[2])
            n_fix1 = cur.rowcount
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {src}").format(src=src_ident))
            n_src = cur.fetchone()[0]
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {out}").format(out=out_ident))
            total = cur.fetchone()[0]
        conn.commit()
        print(f"  source rows:    {n_src}", file=sys.stderr)
        print(f"  troncon rows:   {total}", file=sys.stderr)
        print(f"  PR corrections: {n_fix2} next-fixed, {n_fix1} prev-fixed",
              file=sys.stderr)
        print("Done.", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
