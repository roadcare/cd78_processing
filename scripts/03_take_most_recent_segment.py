"""Keep the most-recent, non-overlapping segments of a source layer.

Reads a source layer (``schema.table``) from the PostgreSQL database in
``config/config.yaml``, resolves overlapping segments so the **most recent**
wins, and writes the result to an output table (default
``<input_table>_most_recent`` in the same schema) with an extra
``is_overlapping`` boolean column.

Overlap is taken from ``overlapping_definition.md``:
- **geometry**: same axe and ``ST_Length(ST_Intersection) > --min-overlap`` m.
- **cumulated distance**: same axe and the ``(cumuld, cumulf)`` intervals
  intersect over a non-zero range.

Rules (see ``take_most_recente_segment_task.md``):
- Non-overlapping segments are copied as-is, ``is_overlapping = false``.
- For an overlapping pair, the *older* one (by ``--date-col``; NULL counts as 0,
  ties broken by larger ``id`` = newer) is the loser:
  - **overlap in geometry** (with or without cumul): the newer segment is kept
    unchanged; the older is clipped to the part **not** covered by the newer
    (``ST_Difference``). When the pair also overlaps in cumul, the clipped
    pieces' ``cumuld`` / ``cumulf`` are recomputed from their position along the
    older line so the kept part no longer overlaps in either sense. A newer
    segment landing in the middle of the older yields two output rows.
  - **overlap in cumulated distance only** (geometries apart): both segments are
    copied unchanged with ``is_overlapping = true`` (flagged for review).

The script reads the source read-only and rebuilds the output table in a single
transaction.

Usage
-----
    python scripts/03_take_most_recent_segment.py \\
        --source client.20250916_trafic --date-col annee
    python scripts/03_take_most_recent_segment.py \\
        --source client.20250916_trafic --date-col annee \\
        --output client.trafic_clean --min-overlap 1.0
    python scripts/03_take_most_recent_segment.py \\
        --source client.20250916_trafic --date-col annee --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2 import sql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Config / connection  (same pattern as the sibling scripts)
# ---------------------------------------------------------------------------

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
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        dbname=cfg["database"],
    )


def parse_source(source: str) -> tuple[str, str]:
    parts = source.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected 'schema.table', got: {source!r}")
    return parts[0], parts[1]


def to_year(v: Any) -> float:
    """Recency key. NULL -> 0; numeric/year strings -> float; dates -> ordinal."""
    if v is None:
        return 0.0
    if isinstance(v, (date, datetime)):
        return float(v.toordinal())
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_columns(cur, schema: str, table: str) -> list[str]:
    cur.execute(
        """
        SELECT a.attname
        FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    )
    return [r["attname"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Classification — find overlapping pairs and assign loser / winner
# ---------------------------------------------------------------------------

def build_pair_query(
    schema: str, table: str, id_col: str, axe_col: str, geom_col: str,
    cumuld_col: str, cumulf_col: str, date_col: str,
) -> sql.Composed:
    ids = {k: sql.Identifier(v) for k, v in
           {"schema": schema, "table": table, "id": id_col, "axe": axe_col,
            "geom": geom_col, "cd": cumuld_col, "cf": cumulf_col,
            "date": date_col}.items()}
    return sql.SQL(
        """
        SELECT t1.{id} AS id1, t2.{id} AS id2,
               t1.{date} AS d1, t2.{date} AS d2,
               t1.{cd} AS cd1, t1.{cf} AS cf1,
               t2.{cd} AS cd2, t2.{cf} AS cf2,
               (ST_Intersects(t1.{geom}, t2.{geom})
                AND ST_Length(ST_Intersection(t1.{geom}, t2.{geom})) > %(min)s)
                                                                       AS geom_ov,
               (GREATEST(LEAST(t1.{cd}, t1.{cf}), LEAST(t2.{cd}, t2.{cf}))
                  < LEAST(GREATEST(t1.{cd}, t1.{cf}), GREATEST(t2.{cd}, t2.{cf})))
                                                                       AS cumul_ov
        FROM {schema}.{table} t1
        JOIN {schema}.{table} t2
          ON t1.{axe} = t2.{axe} AND t1.{id} < t2.{id}
        WHERE ST_Intersects(t1.{geom}, t2.{geom})
           OR (GREATEST(LEAST(t1.{cd}, t1.{cf}), LEAST(t2.{cd}, t2.{cf}))
                 < LEAST(GREATEST(t1.{cd}, t1.{cf}), GREATEST(t2.{cd}, t2.{cf})))
        """
    ).format(**ids)


def classify(cur, query: sql.Composed, min_overlap: float) -> dict[str, Any]:
    """Return the disposition of every segment that takes part in an overlap.

    - ``clip_both``  : older_id -> set(newer ids) for pairs overlapping in both
    - ``clip_geom``  : older_id -> set(newer ids) for geometry-only pairs
    - ``cumul_only`` : set of ids in cumul-only pairs
    - ``cumul``      : id -> (lo, hi) normalised cumul interval (for clipping)
    """
    cur.execute(query, {"min": min_overlap})
    clip_both: dict[int, set[int]] = {}
    clip_geom: dict[int, set[int]] = {}
    cumul_only: set[int] = set()
    cumul: dict[int, tuple[float, float]] = {}

    for r in cur.fetchall():
        cumul[r["id1"]] = (min(r["cd1"], r["cf1"]), max(r["cd1"], r["cf1"]))
        cumul[r["id2"]] = (min(r["cd2"], r["cf2"]), max(r["cd2"], r["cf2"]))
        g, c = bool(r["geom_ov"]), bool(r["cumul_ov"])
        if not (g or c):
            continue
        y1, y2 = to_year(r["d1"]), to_year(r["d2"])
        if y1 < y2:
            older, newer = r["id1"], r["id2"]
        elif y2 < y1:
            older, newer = r["id2"], r["id1"]
        else:  # tie -> larger id is the newer one
            older, newer = sorted((r["id1"], r["id2"]))

        if g and c:
            clip_both.setdefault(older, set()).add(newer)
        elif g:  # geometry-only
            clip_geom.setdefault(older, set()).add(newer)
        else:    # cumul-only
            cumul_only.update((r["id1"], r["id2"]))

    return {"clip_both": clip_both, "clip_geom": clip_geom,
            "cumul_only": cumul_only, "cumul": cumul}


def subtract_intervals(
    base: tuple[float, float], holes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Return the parts of ``base`` left after removing every interval in
    ``holes``. Used to compute an older segment's surviving cumul ranges."""
    segs = [base]
    for hl, hh in holes:
        nxt: list[tuple[float, float]] = []
        for a, b in segs:
            if hh <= a or hl >= b:        # no overlap
                nxt.append((a, b))
                continue
            if hl > a:                    # piece before the hole
                nxt.append((a, hl))
            if hh < b:                    # piece after the hole
                nxt.append((hh, b))
        segs = nxt
    return [(a, b) for a, b in segs if b - a > 0]


# ---------------------------------------------------------------------------
# Output-table SQL builders
# ---------------------------------------------------------------------------

def setup_statements(
    src: sql.Composed, out: sql.Composed, id_col: str
) -> list[sql.Composed]:
    """Drop + recreate the output table.

    The source ``id`` column is renamed to ``source_id`` (kept for traceability;
    not unique, since a clipped segment may appear on more than one row), and a
    fresh ``id`` is added as the generated, unique PRIMARY KEY.
    """
    return [
        sql.SQL("DROP TABLE IF EXISTS {out} CASCADE").format(out=out),
        # plain LIKE copies columns/types/NOT NULL but not the source PK.
        sql.SQL("CREATE TABLE {out} (LIKE {src})").format(out=out, src=src),
        sql.SQL("ALTER TABLE {out} RENAME COLUMN {id} TO source_id").format(
            out=out, id=sql.Identifier(id_col)),
        sql.SQL(
            "ALTER TABLE {out} "
            "ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
        ).format(out=out),
        sql.SQL(
            "ALTER TABLE {out} ADD COLUMN is_overlapping boolean DEFAULT false"
        ).format(out=out),
    ]


def _out_collist(columns: list[str], id_col: str) -> sql.Composed:
    """Target column list for the source columns, with ``id_col`` mapped to
    ``source_id`` (the new generated ``id`` is omitted so it auto-fills)."""
    return sql.SQL(", ").join(
        sql.Identifier("source_id" if c == id_col else c) for c in columns)


def _select_items(
    columns: list[str], geom_expr: sql.Composed,
    cumuld_expr: sql.Composed, cumulf_expr: sql.Composed,
    geom_col: str, cumuld_col: str, cumulf_col: str,
) -> sql.Composed:
    items: list[sql.Composed] = []
    for col in columns:
        if col == geom_col:
            items.append(geom_expr)
        elif col == cumuld_col:
            items.append(cumuld_expr)
        elif col == cumulf_col:
            items.append(cumulf_expr)
        else:
            items.append(sql.SQL("o.{}").format(sql.Identifier(col)))
    return sql.SQL(", ").join(items)


def build_clip_both(
    src: sql.Composed, out: sql.Composed, columns: list[str],
    id_col: str, geom_col: str, cumuld_col: str, cumulf_col: str,
) -> sql.Composed:
    """Insert ONE surviving cumul sub-interval ``[%(a)s, %(b)s]`` of an older
    segment. The geometry is the matching portion of the older line
    (``ST_LineSubstring``) with the geometry of **every** newer
    geometry-overlapping partner (ids ``%(pids)s``) subtracted — so the kept
    part overlaps no newer segment in either cumulated distance *or* geometry,
    even when the line is not perfectly proportional to cumul. ``cumuld`` /
    ``cumulf`` become the sub-interval bounds."""
    g, cd, cf = (sql.Identifier(geom_col), sql.Identifier(cumuld_col),
                 sql.Identifier(cumulf_col))
    geom_expr = sql.SQL("ST_Multi(pc.pg)")
    cumuld_expr = sql.SQL("%(a)s::bigint")
    cumulf_expr = sql.SQL("%(b)s::bigint")
    sel = _select_items(columns, geom_expr, cumuld_expr, cumulf_expr,
                         geom_col, cumuld_col, cumulf_col)
    collist = _out_collist(columns, id_col)
    return sql.SQL(
        """
        WITH o AS (SELECT * FROM {src} WHERE {id} = %(oid)s),
             u AS (SELECT ST_Union({g}) AS g FROM {src}
                    WHERE {id} = ANY(%(pids)s::int[])),
             ln AS (SELECT ST_LineMerge((SELECT {g} FROM o)) AS line,
                           LEAST((SELECT {cd} FROM o),
                                 (SELECT {cf} FROM o))::numeric AS lo,
                           GREATEST((SELECT {cd} FROM o),
                                    (SELECT {cf} FROM o))::numeric AS hi),
             pc AS (SELECT ST_CollectionExtract(
                            ST_Difference(
                              ST_LineSubstring(
                                ln.line,
                                GREATEST(0, LEAST(1, (%(a)s - ln.lo)
                                                     / NULLIF(ln.hi - ln.lo, 0))),
                                GREATEST(0, LEAST(1, (%(b)s - ln.lo)
                                                     / NULLIF(ln.hi - ln.lo, 0)))),
                              (SELECT g FROM u)), 2) AS pg
                    FROM ln
                    WHERE ST_GeometryType(ln.line) = 'ST_LineString')
        INSERT INTO {out} ({collist}, is_overlapping)
        SELECT {sel}, false
        FROM o, pc
        WHERE ST_Length(pc.pg) > %(minlen)s
        """
    ).format(src=src, out=out, id=sql.Identifier(id_col), g=g, cd=cd, cf=cf,
             collist=collist, sel=sel)


def build_clip_geom(
    src: sql.Composed, out: sql.Composed, columns: list[str],
    id_col: str, geom_col: str, cumuld_col: str, cumulf_col: str,
) -> sql.Composed:
    """Clip an older segment whose only overlap with newer partners is
    geometric: subtract their geometry, keep cumul unchanged, one row."""
    g = sql.Identifier(geom_col)
    diff = sql.SQL(
        "ST_CollectionExtract(ST_Difference(o.{g}, (SELECT g FROM u)), 2)"
    ).format(g=g)
    geom_expr = sql.SQL("ST_Multi({diff})").format(diff=diff)
    cumuld_expr = sql.SQL("o.{}").format(sql.Identifier(cumuld_col))
    cumulf_expr = sql.SQL("o.{}").format(sql.Identifier(cumulf_col))
    sel = _select_items(columns, geom_expr, cumuld_expr, cumulf_expr,
                        geom_col, cumuld_col, cumulf_col)
    collist = _out_collist(columns, id_col)
    return sql.SQL(
        """
        WITH o AS (SELECT * FROM {src} WHERE {id} = %(oid)s),
             u AS (SELECT ST_Union({g}) AS g FROM {src}
                    WHERE {id} = ANY(%(pids)s::int[]))
        INSERT INTO {out} ({collist}, is_overlapping)
        SELECT {sel}, false
        FROM o
        WHERE ST_Length({diff}) > 0
        """
    ).format(src=src, out=out, id=sql.Identifier(id_col), g=g,
             collist=collist, sel=sel, diff=diff)


def build_copy_unchanged(
    src: sql.Composed, out: sql.Composed, columns: list[str], id_col: str,
    *, flag: bool,
) -> sql.Composed:
    """Copy whole source rows, mapping the source id into ``source_id`` and
    appending the is_overlapping flag (the new ``id`` auto-fills).

    When ``flag`` is true: only the ``flagged`` ids (cumul-only members).
    When false: everything that is neither clipped nor flagged.
    """
    idc = sql.Identifier(id_col)
    if flag:
        where = sql.SQL("s.{id} = ANY(%(flagged)s::int[])").format(id=idc)
    else:
        where = sql.SQL(
            "NOT (s.{id} = ANY(%(clipped)s::int[])) "
            "AND NOT (s.{id} = ANY(%(flagged)s::int[]))"
        ).format(id=idc)
    collist = _out_collist(columns, id_col)
    return sql.SQL(
        "INSERT INTO {out} ({collist}, is_overlapping) "
        "SELECT s.*, {flag} FROM {src} s WHERE {where}"
    ).format(out=out, src=src, collist=collist, flag=sql.Literal(flag),
             where=where)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml"
    )
    parser.add_argument("--source", required=True,
                        help="Source layer 'schema.table'.")
    parser.add_argument("--date-col", required=True,
                        help="Recency column (e.g. annee).")
    parser.add_argument("--axe-col", default="axe")
    parser.add_argument("--cumuld-col", default="cumuld")
    parser.add_argument("--cumulf-col", default="cumulf")
    parser.add_argument("--geom-col", default="geom")
    parser.add_argument("--id-col", default="id")
    parser.add_argument("--min-overlap", type=float, default=1.0,
                        help="Geometry overlap threshold in metres (default 1.0).")
    parser.add_argument("--output", default=None,
                        help="Output table 'schema.table' "
                             "(default <source>_most_recent in the same schema).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without changing the DB.")
    args = parser.parse_args(argv)

    schema, table = parse_source(args.source)
    if args.output:
        out_schema, out_table = parse_source(args.output)
    else:
        out_schema, out_table = schema, f"{table}_most_recent"

    cfg = load_config(args.config)
    src_ident = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    out_ident = sql.SQL("{}.{}").format(
        sql.Identifier(out_schema), sql.Identifier(out_table))

    print(f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
          file=sys.stderr)
    print(f"Source: {schema}.{table}  ->  Output: {out_schema}.{out_table}",
          file=sys.stderr)

    conn = connect(cfg)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            columns = fetch_columns(cur, schema, table)
            if args.id_col not in columns:
                print(f"ERROR: id column {args.id_col!r} not in {table}",
                      file=sys.stderr)
                return 2
            pair_q = build_pair_query(
                schema, table, args.id_col, args.axe_col, args.geom_col,
                args.cumuld_col, args.cumulf_col, args.date_col)
            cls = classify(cur, pair_q, args.min_overlap)

        clip_both = cls["clip_both"]
        clip_geom = cls["clip_geom"]
        clipped_ids = sorted(set(clip_both) | set(clip_geom))
        flagged_ids = sorted(cls["cumul_only"] - set(clipped_ids))

        print(f"  clip (both):      {len(clip_both)} older segment(s)",
              file=sys.stderr)
        print(f"  clip (geom-only): {len(clip_geom)} older segment(s)",
              file=sys.stderr)
        print(f"  cumul-only flag:  {len(flagged_ids)} segment(s)",
              file=sys.stderr)

        setup = setup_statements(src_ident, out_ident, args.id_col)
        copy_false = build_copy_unchanged(src_ident, out_ident, columns,
                                          args.id_col, flag=False)
        copy_true = build_copy_unchanged(src_ident, out_ident, columns,
                                         args.id_col, flag=True)
        clip_both_sql = build_clip_both(src_ident, out_ident, columns,
                                        args.id_col, args.geom_col,
                                        args.cumuld_col, args.cumulf_col)
        clip_geom_sql = build_clip_geom(src_ident, out_ident, columns,
                                        args.id_col, args.geom_col,
                                        args.cumuld_col, args.cumulf_col)

        if args.dry_run:
            with conn.cursor() as cur:
                for s in setup:
                    print("\n" + s.as_string(cur) + ";", file=sys.stderr)
                print("\n-- copy non-overlapping / winners (is_overlapping=false) --",
                      file=sys.stderr)
                print(copy_false.as_string(cur) + ";", file=sys.stderr)
                print("\n-- copy cumul-only pairs (is_overlapping=true) --",
                      file=sys.stderr)
                print(copy_true.as_string(cur) + ";", file=sys.stderr)
                if clip_both:
                    print("\n-- clip older (both) — per older id --", file=sys.stderr)
                    print(clip_both_sql.as_string(cur) + ";", file=sys.stderr)
                if clip_geom:
                    print("\n-- clip older (geometry-only) — per older id --",
                          file=sys.stderr)
                    print(clip_geom_sql.as_string(cur) + ";", file=sys.stderr)
            conn.rollback()
            return 0

        inserted = 0
        with conn.cursor() as cur:
            for s in setup:
                cur.execute(s)

            cur.execute(copy_false, {"clipped": clipped_ids,
                                     "flagged": flagged_ids})
            inserted += cur.rowcount
            cur.execute(copy_true, {"flagged": flagged_ids})
            inserted += cur.rowcount

            line_check = sql.SQL(
                "SELECT ST_GeometryType(ST_LineMerge({g})) = 'ST_LineString' "
                "FROM {src} WHERE {id} = %s"
            ).format(g=sql.Identifier(args.geom_col), src=src_ident,
                     id=sql.Identifier(args.id_col))

            # Clip "both"-overlap olders by removing each newer partner's cumul
            # interval (one row per surviving sub-interval) AND subtracting the
            # geometry of every geometry-overlapping newer partner (both +
            # geometry-only) so no geometric overlap can survive.
            cumul = cls["cumul"]
            for oid, both_partners in clip_both.items():
                holes = sorted(cumul[p] for p in both_partners)
                surviving = subtract_intervals(cumul[oid], holes)
                if not surviving:
                    continue  # fully covered by newer segments -> dropped
                pids = sorted(both_partners | clip_geom.get(oid, set()))
                cur.execute(line_check, (oid,))
                is_line = cur.fetchone()[0]
                if is_line:
                    for a, b in surviving:
                        cur.execute(clip_both_sql,
                                    {"oid": oid, "a": int(round(a)),
                                     "b": int(round(b)), "pids": pids,
                                     "minlen": args.min_overlap})
                        inserted += cur.rowcount
                else:
                    # multi-part line: fall back to geometry difference,
                    # leaving cumul as-is (one row).
                    print(f"  WARN: id {oid} not a single line; clip(both) "
                          f"fell back to geometry difference.", file=sys.stderr)
                    cur.execute(clip_geom_sql, {"oid": oid, "pids": pids})
                    inserted += cur.rowcount

            # Clip geometry-only olders: subtract partner geometry, cumul as-is.
            for oid, geom_partners in clip_geom.items():
                if oid in clip_both:
                    continue  # handled above (geom-only partners folded in)
                cur.execute(clip_geom_sql, {"oid": oid,
                                            "pids": sorted(geom_partners)})
                inserted += cur.rowcount

            cur.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {out}").format(out=out_ident))
            total = cur.fetchone()[0]

        conn.commit()
        print(f"  inserted rows:    {inserted}", file=sys.stderr)
        print(f"  output total:     {total}", file=sys.stderr)
        print("Done.", file=sys.stderr)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
