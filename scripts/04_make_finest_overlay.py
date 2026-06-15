"""Build the finest linear-referencing overlay of >=2 source tables.

Each source table shares four columns (``axe``, ``cumuld``, ``cumulf``,
``geom``) and contributes one *considered value* column (e.g. ``nb_pl`` for the
traffic layer, ``nature_cr`` for the road-surface layer). The output table
splits every axe at the union of all segment boundaries so that each output
segment carries exactly one combination of
``(axe, cumuld, cumulf, value_table1, value_table2, ...)``.

Semantics (see ``overlapping_definition.md``):
- **Union / outer** — a segment is emitted wherever *any* source table covers it.
- Each interval's geometry is the clipped geometry of the **first listed table**
  that covers it (the "reference").
- A table's value is attached to an interval only when its covering segment
  **linearly intersects** that reference geometry (``ST_Length(ST_Intersection)
  > 0``); otherwise the value is ``null``. This matches segments on the LRS
  (same axe + overlapping cumul) *and* on geometry, while still keeping
  reference-only stretches.
- If a table has several covering+intersecting segments over one interval, the
  output multiplies (one row per combination across tables). A null source
  attribute stays null.

Output columns: ``id`` (PK), ``axe``, ``cumuld``, ``cumulf``, ``geom``, one
column per source named after its considered column, and (after
post-processing) one ``<considered>_final`` column per source.

Three post-processing steps run automatically after the overlay:
  1. Add a ``<considered>_final`` column per source and copy the raw value.
  2. Where a ``_final`` is null, fill it from (in order) the previous segment of
     the same axe, then the next, then the nearest non-null one (nearest by
     geometry, then cumul). One pass over the original values.
  3. Fuse contiguous same-axe segments that share the same ``_final`` tuple into
     a single segment (geometry merged, cumul extent), dropping the elements;
     the table is rebuilt with a fresh ``id`` primary key.
  4. Add the PR reference columns ``plod``/``absd``/``plof``/``absf`` and fill
     them from an anchor map of every source segment endpoint (exact lookup at
     each fused segment's cumuld / cumulf). Skipped if a source lacks them.

Usage
-----
    python scripts/04_make_finest_overlay.py \\
        --table 'client.20250916_trafic_most_recent:nb_pl' \\
        --table 'client.20260227_couche_roulement:nature_cr'

    python scripts/04_make_finest_overlay.py \\
        --table 'client.20250916_trafic_most_recent:nb_pl' \\
        --table 'client.20260227_couche_roulement:nature_cr' \\
        --output client.my_overlay --dry-run
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
DEFAULT_OUTPUT = 'client.20260301_trafic_couche_roulement_intersection'


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
        password=cfg["password"], dbname=cfg["database"],
    )


def parse_qualified(name: str) -> tuple[str, str]:
    parts = name.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected 'schema.table', got: {name!r}")
    return parts[0], parts[1]


def parse_table_spec(spec: str) -> tuple[str, str, str]:
    """Parse ``schema.table:value_col`` -> (schema, table, value_col)."""
    if ":" not in spec:
        raise ValueError(
            f"--table must be 'schema.table:value_col', got: {spec!r}")
    qualified, value_col = spec.rsplit(":", 1)
    schema, table = parse_qualified(qualified)
    if not value_col:
        raise ValueError(f"--table is missing the value column: {spec!r}")
    return schema, table, value_col


# ---------------------------------------------------------------------------
# SQL building
# ---------------------------------------------------------------------------

def _frac(x: sql.Composed, ivcol: sql.Composed, cd: str, cf: str) -> sql.Composed:
    """Fraction of point ``ivcol`` along table-alias ``x``'s cumul interval."""
    return sql.SQL(
        "GREATEST(0, LEAST(1, ({iv} - LEAST(x.{cd}, x.{cf})) "
        "/ NULLIF(GREATEST(x.{cd}, x.{cf}) - LEAST(x.{cd}, x.{cf}), 0)))"
    ).format(iv=ivcol, cd=sql.Identifier(cd), cf=sql.Identifier(cf))


def build_overlay_select(
    tables: list[tuple[sql.Composed, str, str]],  # (ident, value_col, alias)
    axe: str, cd: str, cf: str, geom: str, geom_tol: float,
) -> sql.Composed:
    """Compose the big overlay SELECT. ``tables`` is ordered by priority.

    ``geom_tol`` (metres) is the matching tolerance: a covering segment is
    attached to an interval only if the majority of the interval's reference
    geometry lies within ``geom_tol`` of that segment — robust to the small
    vertex differences ``ST_LineMerge`` introduces (a plain
    ``ST_Intersection`` length test wrongly returns 0 for collinear lines)."""
    A, CD, CF, G = (sql.Identifier(axe), sql.Identifier(cd),
                    sql.Identifier(cf), sql.Identifier(geom))

    cover = sql.SQL(
        "x.{axe} = q.{axe} AND LEAST(x.{cd}, x.{cf}) <= q.a "
        "AND GREATEST(x.{cd}, x.{cf}) >= q.b"
    )

    # 1) breakpoints: every cumuld / cumulf of every table, per axe.
    bp_parts = []
    for ident, _vc, _al in tables:
        bp_parts.append(sql.SQL(
            "SELECT {axe}::text AS axe, {cd}::numeric AS b FROM {t}"
        ).format(axe=A, cd=CD, t=ident))
        bp_parts.append(sql.SQL(
            "SELECT {axe}::text AS axe, {cf}::numeric AS b FROM {t}"
        ).format(axe=A, cf=CF, t=ident))
    bp_union = sql.SQL("\n            UNION ALL\n            ").join(bp_parts)

    # 2) reference geometry per interval: clipped geom of the first covering
    #    table, by listed priority (COALESCE).
    ref_parts = []
    for ident, _vc, _al in tables:
        ref_parts.append(sql.SQL(
            "(SELECT ST_LineSubstring(ST_LineMerge(x.{g}), {fa}, {fb}) "
            "FROM {t} x "
            "WHERE {cover} "
            "AND ST_GeometryType(ST_LineMerge(x.{g})) = 'ST_LineString' "
            "LIMIT 1)"
        ).format(
            g=G, t=ident,
            fa=_frac(sql.SQL("x"), sql.SQL("q.a"), cd, cf),
            fb=_frac(sql.SQL("x"), sql.SQL("q.b"), cd, cf),
            cover=cover.format(axe=A, cd=CD, cf=CF),
        ))
    ref_coalesce = sql.SQL("COALESCE(\n            {}\n          )").format(
        sql.SQL(",\n            ").join(ref_parts))

    # 3) one LEFT JOIN LATERAL per table: covering + geometry-intersecting
    #    segments contribute their value (cross product); else NULL.
    join_parts = []
    distinct_vals = []
    out_vals = []
    notnull_parts = []
    for i, (ident, value_col, alias) in enumerate(tables):
        s = sql.Identifier(f"s{i}")
        al = sql.Identifier(alias)
        notnull_parts.append(sql.SQL("{s}.{al} IS NOT NULL").format(s=s, al=al))
        join_parts.append(sql.SQL(
            "LEFT JOIN LATERAL (\n"
            "    SELECT x.{vc} AS {al}\n"
            "    FROM {t} x\n"
            "    WHERE x.{axe} = r.axe "
            "AND LEAST(x.{cd}, x.{cf}) <= r.a AND GREATEST(x.{cd}, x.{cf}) >= r.b\n"
            "      AND ST_Length(ST_Intersection(r.g, ST_Buffer(x.{g}, %(geom_tol)s)))\n"
            "          > 0.5 * ST_Length(r.g)\n"
            ") {s} ON true"
        ).format(vc=sql.Identifier(value_col), al=al, t=ident, axe=A,
                 cd=CD, cf=CF, g=G, s=s))
        distinct_vals.append(sql.SQL("{s}.{al}").format(s=s, al=al))
        out_vals.append(sql.SQL("ov.{al}").format(al=al))
    joins = sql.SQL("\n        ").join(join_parts)
    distinct_select = sql.SQL(",\n                   ").join(distinct_vals)
    out_select = sql.SQL(",\n               ").join(out_vals)
    not_all_null = sql.SQL(" OR ").join(notnull_parts)

    return sql.SQL(
        """
        WITH bp AS (
            {bp_union}
        ),
        ivb AS (SELECT DISTINCT axe, b FROM bp),
        iv AS (
            SELECT axe, b AS a,
                   LEAD(b) OVER (PARTITION BY axe ORDER BY b) AS b2
            FROM ivb
        ),
        q AS (SELECT axe, a, b2 AS b FROM iv WHERE b2 IS NOT NULL AND b2 > a),
        r AS (SELECT q.axe, q.a, q.b, {ref_coalesce} AS g FROM q),
        ov AS (
            SELECT DISTINCT r.axe AS axe, r.a AS a, r.b AS b, r.g AS g,
                   {distinct_select}
            FROM r
            {joins}
            WHERE r.g IS NOT NULL AND ({not_all_null})
        )
        SELECT row_number() OVER (ORDER BY ov.axe, ov.a) AS id,
               ov.axe                                    AS {axe},
               ov.a::bigint                              AS {cd},
               ov.b::bigint                              AS {cf},
               ST_Multi(ov.g)::geometry(MultiLineString, 3949) AS {geom},
               {out_select}
        FROM ov
        """
    ).format(bp_union=bp_union, ref_coalesce=ref_coalesce,
             axe=A, cd=CD, cf=CF, geom=G,
             distinct_select=distinct_select, joins=joins,
             not_all_null=not_all_null, out_select=out_select)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def fetch_value_type(cur, schema: str, table: str, col: str) -> str:
    cur.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attname = %s
        """,
        (schema, table, col),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"column {col!r} not found in {schema}.{table}")
    return row[0]


def build_step1(out: sql.Composed,
                finals: list[tuple[str, str, str]]) -> list[sql.Composed]:
    """Step 1 — add a ``<value>_final`` column per source and copy the value."""
    stmts: list[sql.Composed] = []
    for alias, final, typ in finals:
        stmts.append(sql.SQL("ALTER TABLE {out} ADD COLUMN {fin} {typ}").format(
            out=out, fin=sql.Identifier(final), typ=sql.SQL(typ)))
        stmts.append(sql.SQL("UPDATE {out} SET {fin} = {src}").format(
            out=out, fin=sql.Identifier(final), src=sql.Identifier(alias)))
    return stmts


def build_step2(out: sql.Composed, final: str) -> sql.Composed:
    """Step 2 — fill a null ``<value>_final`` from, in order, the previous
    segment of the same axe, then the next, then the nearest non-null one
    (nearest by geometry, then cumul). Single pass over the original values."""
    f = sql.Identifier(final)
    return sql.SQL(
        """
        WITH base AS (
            SELECT id, axe, cumuld, geom, {f} AS v,
                   LAG({f})  OVER w AS prev_v,
                   LEAD({f}) OVER w AS next_v
            FROM {out}
            WINDOW w AS (PARTITION BY axe ORDER BY cumuld, cumulf, id)
        )
        UPDATE {out} o
           SET {f} = COALESCE(
                 b.prev_v,
                 b.next_v,
                 (SELECT n.{f} FROM {out} n
                   WHERE n.axe = b.axe AND n.{f} IS NOT NULL AND n.id <> b.id
                   ORDER BY ST_Distance(n.geom, b.geom), abs(n.cumuld - b.cumuld)
                   LIMIT 1))
          FROM base b
         WHERE o.id = b.id AND b.v IS NULL
        """
    ).format(f=f, out=out)


def build_step3(out: sql.Composed, fused: sql.Composed, out_table: str,
                aliases: list[str], finals: list[str]) -> list[sql.Composed]:
    """Step 3 — fuse contiguous same-axe segments sharing the same ``_final``
    tuple into one segment (geometry merged, cumul extent), dropping the
    element rows. Rebuilds the output table with fresh ``id`` PRIMARY KEY."""
    final_ids = sql.SQL(", ").join(sql.Identifier(f) for f in finals)
    part_by = sql.SQL("axe, {}").format(final_ids)
    orig_aggs = sql.SQL(", ").join(
        sql.SQL("max({a}) AS {a}").format(a=sql.Identifier(a)) for a in aliases)
    final_keys = final_ids
    plain_cols = sql.SQL(", ").join(
        sql.Identifier(c) for c in (*aliases, *finals))
    create = sql.SQL(
        """
        CREATE TABLE {fused} AS
        SELECT row_number() OVER (ORDER BY axe, cumuld) AS id,
               axe, cumuld, cumulf, geom, {plain_cols}
        FROM (
            SELECT axe, min(cumuld) AS cumuld, max(cumulf) AS cumulf,
                   ST_Multi(ST_LineMerge(ST_Union(geom)))::geometry(MultiLineString, 3949) AS geom,
                   {orig_aggs}, {final_keys}
            FROM (
                SELECT *, SUM(isnew) OVER (PARTITION BY {part_by}
                                           ORDER BY cumuld, cumulf) AS gid
                FROM (
                    SELECT *, CASE WHEN cumuld > LAG(cumulf) OVER (
                                       PARTITION BY {part_by}
                                       ORDER BY cumuld, cumulf)
                                   THEN 1 ELSE 0 END AS isnew
                    FROM {out}
                ) s1
            ) s2
            GROUP BY axe, {final_keys}, gid
        ) f
        """
    ).format(fused=fused, out=out, orig_aggs=orig_aggs, final_keys=final_keys,
             part_by=part_by, plain_cols=plain_cols)
    return [
        create,
        sql.SQL("DROP TABLE {out} CASCADE").format(out=out),
        sql.SQL("ALTER TABLE {fused} RENAME TO {bare}").format(
            fused=fused, bare=sql.Identifier(out_table)),
        sql.SQL("ALTER TABLE {out} ADD PRIMARY KEY (id)").format(out=out),
    ]


PR_COLS = ("plod", "absd", "plof", "absf")


def build_step4_pr(out: sql.Composed, tables: list[tuple[sql.Composed, str, str]],
                   axe: str, cd: str, cf: str,
                   plod_type: str, absd_type: str) -> list[sql.Composed]:
    """Step 4 — add the PR reference columns (``plod``/``absd``/``plof``/``absf``)
    and populate them from an anchor map of every source segment endpoint across
    all input tables (exact lookup at each fused segment's cumuld / cumulf)."""
    A, CD, CF = sql.Identifier(axe), sql.Identifier(cd), sql.Identifier(cf)
    PLOD, ABSD, PLOF, ABSF = (sql.Identifier("plod"), sql.Identifier("absd"),
                              sql.Identifier("plof"), sql.Identifier("absf"))
    adds = [
        sql.SQL("ALTER TABLE {out} ADD COLUMN {c} {t}").format(
            out=out, c=PLOD, t=sql.SQL(plod_type)),
        sql.SQL("ALTER TABLE {out} ADD COLUMN {c} {t}").format(
            out=out, c=ABSD, t=sql.SQL(absd_type)),
        sql.SQL("ALTER TABLE {out} ADD COLUMN {c} {t}").format(
            out=out, c=PLOF, t=sql.SQL(plod_type)),
        sql.SQL("ALTER TABLE {out} ADD COLUMN {c} {t}").format(
            out=out, c=ABSF, t=sql.SQL(absd_type)),
    ]
    parts = []
    for ident, _vc, _al in tables:
        parts.append(sql.SQL(
            "SELECT {A} AS axe, {CD} AS cml, {PLOD} AS plo, {ABSD} AS abs FROM {t}"
        ).format(A=A, CD=CD, PLOD=PLOD, ABSD=ABSD, t=ident))
        parts.append(sql.SQL(
            "SELECT {A}, {CF}, {PLOF}, {ABSF} FROM {t}"
        ).format(A=A, CF=CF, PLOF=PLOF, ABSF=ABSF, t=ident))
    anchors_union = sql.SQL("\n                UNION ALL\n                ").join(parts)
    update = sql.SQL(
        """
        WITH anchors AS (
            SELECT DISTINCT ON (axe, cml) axe, cml, plo, abs
            FROM (
                {anchors_union}
            ) u
            WHERE plo IS NOT NULL
            ORDER BY axe, cml, plo, abs
        )
        UPDATE {out} o SET
            {PLOD} = (SELECT plo FROM anchors a WHERE a.axe = o.{A} AND a.cml = o.{CD}),
            {ABSD} = (SELECT abs FROM anchors a WHERE a.axe = o.{A} AND a.cml = o.{CD}),
            {PLOF} = (SELECT plo FROM anchors a WHERE a.axe = o.{A} AND a.cml = o.{CF}),
            {ABSF} = (SELECT abs FROM anchors a WHERE a.axe = o.{A} AND a.cml = o.{CF})
        """
    ).format(anchors_union=anchors_union, out=out, A=A, CD=CD, CF=CF,
             PLOD=PLOD, ABSD=ABSD, PLOF=PLOF, ABSF=ABSF)
    return adds + [update]


def has_columns(cur, schema: str, table: str, cols: tuple[str, ...]) -> bool:
    cur.execute(
        """
        SELECT count(*) FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attname = ANY(%s)
          AND a.attnum > 0 AND NOT a.attisdropped
        """,
        (schema, table, list(cols)),
    )
    return cur.fetchone()[0] == len(cols)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument(
        "--table", action="append", default=[], metavar="SCHEMA.TABLE:VALUE_COL",
        help="A source table and its considered-value column. Repeat (>=2); "
             "order sets reference priority.")
    parser.add_argument("--axe-col", default="axe")
    parser.add_argument("--cumuld-col", default="cumuld")
    parser.add_argument("--cumulf-col", default="cumulf")
    parser.add_argument("--geom-col", default="geom")
    parser.add_argument("--geom-tol", type=float, default=2.0,
                        help="Geometry matching tolerance in metres (default 2.0): "
                             "a segment's value is attached only if most of an "
                             "interval's reference geometry is within this distance.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Output 'schema.table' (default {DEFAULT_OUTPUT}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and exit without changes.")
    args = parser.parse_args(argv)

    if len(args.table) < 2:
        print("ERROR: at least two --table specs are required.", file=sys.stderr)
        return 2

    specs = [parse_table_spec(t) for t in args.table]
    # Unique output value-column aliases (suffix on collision).
    used: set[str] = set()
    tables: list[tuple[sql.Composed, str, str]] = []
    for schema, table, value_col in specs:
        alias = value_col
        n = 2
        while alias in used:
            alias = f"{value_col}_{n}"
            n += 1
        used.add(alias)
        ident = sql.SQL("{}.{}").format(
            sql.Identifier(schema), sql.Identifier(table))
        tables.append((ident, value_col, alias))

    out_schema, out_table = parse_qualified(args.output)
    out_ident = sql.SQL("{}.{}").format(
        sql.Identifier(out_schema), sql.Identifier(out_table))

    cfg = load_config(args.config)
    select = build_overlay_select(
        tables, args.axe_col, args.cumuld_col, args.cumulf_col, args.geom_col,
        args.geom_tol)

    drop = sql.SQL("DROP TABLE IF EXISTS {out} CASCADE").format(out=out_ident)
    create = sql.SQL("CREATE TABLE {out} AS {select}").format(
        out=out_ident, select=select)
    add_pk = sql.SQL("ALTER TABLE {out} ADD PRIMARY KEY (id)").format(out=out_ident)

    fused_ident = sql.SQL("{}.{}").format(
        sql.Identifier(out_schema), sql.Identifier(f"__fused_{out_table}"))
    aliases = [al for _i, _v, al in tables]

    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    print(f"Overlay of {len(tables)} tables -> {out_schema}.{out_table}",
          file=sys.stderr)
    conn = connect(cfg)
    conn.autocommit = False
    try:
        for (schema, table, value_col), (_ident, _vc, alias) in zip(specs, tables):
            print(f"  {schema}.{table}: value '{value_col}' -> column "
                  f"'{alias}'", file=sys.stderr)

        # Resolve each value column's type (for the _final columns) from source,
        # and decide whether the PR columns can be added (present in every table).
        with conn.cursor() as cur:
            finals = [(alias, f"{alias}_final",
                       fetch_value_type(cur, schema, table, value_col))
                      for (schema, table, value_col), (_i, _v, alias)
                      in zip(specs, tables)]
            have_pr = all(has_columns(cur, s, t, PR_COLS) for s, t, _v in specs)
            if have_pr:
                s0, t0, _v0 = specs[0]
                plod_type = fetch_value_type(cur, s0, t0, "plod")
                absd_type = fetch_value_type(cur, s0, t0, "absd")
        final_names = [f for _a, f, _t in finals]

        step1 = build_step1(out_ident, finals)
        step2 = [build_step2(out_ident, f) for f in final_names]
        step3 = build_step3(out_ident, fused_ident, out_table, aliases, final_names)
        step4 = (build_step4_pr(out_ident, tables, args.axe_col, args.cumuld_col,
                                args.cumulf_col, plod_type, absd_type)
                 if have_pr else [])

        if args.dry_run:
            with conn.cursor() as cur:
                for label, stmts in (("create", [drop, create, add_pk]),
                                     ("post step 1 (add _final)", step1),
                                     ("post step 2 (fill nulls)", step2),
                                     ("post step 3 (fuse)", step3),
                                     ("post step 4 (PR cols)", step4)):
                    print(f"\n-- {label} --", file=sys.stderr)
                    for s in stmts:
                        print(s.as_string(cur) + ";", file=sys.stderr)
            conn.rollback()
            return 0

        with conn.cursor() as cur:
            cur.execute(drop)
            cur.execute(create, {"geom_tol": args.geom_tol})
            cur.execute(add_pk)
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {out}").format(out=out_ident))
            n_overlay = cur.fetchone()[0]
            for s in step1:
                cur.execute(s)
            n_filled = 0
            for s in step2:
                cur.execute(s)
                n_filled += cur.rowcount
            for s in step3:
                cur.execute(s)
            cur.execute(sql.SQL("SELECT COUNT(*) FROM {out}").format(out=out_ident))
            n_fused = cur.fetchone()[0]
            for s in step4:
                cur.execute(s)
        conn.commit()
        print(f"  overlay rows:      {n_overlay}", file=sys.stderr)
        print(f"  _final null fills: {n_filled}", file=sys.stderr)
        print(f"  rows after fusion: {n_fused}", file=sys.stderr)
        print(f"  PR columns:        {'added' if step4 else 'skipped (missing in a source)'}",
              file=sys.stderr)
        print("Done.", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
