"""Analyse overlapping segments in a source layer.

Reads a single source layer (``schema.table``) from the PostgreSQL database
described in ``config/config.yaml`` and reports every pair of segments that
**overlap**, in two independent senses (see ``overlapping_definition.md``):

1. **Geometry overlap** — two segments t1, t2 belong to the same axe
   (``t1.axe = t2.axe``) and ``ST_Length(ST_Intersection(t1.geom, t2.geom))``
   is greater than ``--min-overlap`` metres (default 1 m). A mere crossing
   (point intersection, length 0) does not count.

2. **Cumulated-distance overlap** — two segments belong to the same axe and
   their cumul intervals ``(t1.cumuld, t1.cumulf)`` and ``(t2.cumuld,
   t2.cumulf)`` intersect over a non-zero range. Example: ``(3, 15)`` and
   ``(10, 28)`` overlap from ``10`` to ``15``.

The script is **read-only** — it issues plain ``SELECT``s and never writes to
the database. Results are written to two sibling files derived from
``--output``: a ``.csv`` (one row per overlapping pair) and a ``.md`` summary.

Usage
-----
    python scripts/02_analyse_overlapping.py --source client.20250916_trafic
    python scripts/02_analyse_overlapping.py --source public.road_data \\
        --axe-col axe --cumuld-col cumuld --cumulf-col cumulf --geom-col geom
    python scripts/02_analyse_overlapping.py --source client.20250916_trafic \\
        --type cumul --output reports/trafic_overlap.csv
    python scripts/02_analyse_overlapping.py --source client.20250916_trafic --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2 import sql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# CSV / report column order. One row per pair; ``overlap_type`` is one of
# "geometry", "accumulated distance", or "both". The optional ``t1_date`` /
# ``t2_date`` columns are inserted right after ``id2`` only when --date-col is
# given.
BASE_FIELDNAMES = [
    "overlap_type",
    "axe",
    "id1",
    "id2",
    "t1_cumuld",
    "t1_cumulf",
    "t2_cumuld",
    "t2_cumulf",
    "geom_overlap_length",
    "cumul_overlap_start",
    "cumul_overlap_end",
    "cumul_overlap_length",
]


def build_fieldnames(with_date: bool) -> list[str]:
    """Column order, optionally including the date columns after ``id2``."""
    cols = list(BASE_FIELDNAMES)
    if with_date:
        cols[cols.index("id2") + 1:cols.index("id2") + 1] = ["t1_date", "t2_date"]
    return cols


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
    """Split ``schema.table`` into ``(schema, table)``."""
    parts = source.split(".")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"--source must be 'schema.table', got: {source!r}"
        )
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _date_select(date_col: str | None) -> sql.Composable:
    """``t1.<date> AS t1_date, t2.<date> AS t2_date,`` or empty SQL."""
    if not date_col:
        return sql.SQL("")
    d = sql.Identifier(date_col)
    return sql.SQL("t1.{d} AS t1_date, t2.{d} AS t2_date,").format(d=d)


def build_geometry_query(
    schema: str, table: str, id_col: str, axe_col: str, geom_col: str,
    cumuld_col: str, cumulf_col: str, date_col: str | None = None,
) -> sql.Composed:
    """Pairs on the same axe whose geometries overlap (length > threshold).

    ``ST_Intersects`` is an index-friendly pre-filter; the expensive
    ``ST_Intersection`` length test only runs on candidate pairs.
    """
    ids = {k: sql.Identifier(v) for k, v in
           {"schema": schema, "table": table, "id": id_col, "axe": axe_col,
            "geom": geom_col, "cumuld": cumuld_col, "cumulf": cumulf_col}.items()}
    return sql.SQL(
        """
        SELECT t1.{id}     AS id1,
               t2.{id}     AS id2,
               t1.{axe}    AS axe,
               {date_select}
               t1.{cumuld} AS t1_cumuld,
               t1.{cumulf} AS t1_cumulf,
               t2.{cumuld} AS t2_cumuld,
               t2.{cumulf} AS t2_cumulf,
               ST_Length(ST_Intersection(t1.{geom}, t2.{geom})) AS overlap_length
        FROM {schema}.{table} t1
        JOIN {schema}.{table} t2
          ON t1.{axe} = t2.{axe}
         AND t1.{id} < t2.{id}
         AND ST_Intersects(t1.{geom}, t2.{geom})
        WHERE ST_Length(ST_Intersection(t1.{geom}, t2.{geom})) > %(min_overlap)s
        ORDER BY t1.{axe}, t1.{id}, t2.{id}
        """
    ).format(date_select=_date_select(date_col), **ids)


def build_cumul_query(
    schema: str, table: str, id_col: str, axe_col: str,
    cumuld_col: str, cumulf_col: str, date_col: str | None = None,
) -> sql.Composed:
    """Pairs on the same axe whose cumul intervals intersect over a range.

    Each segment's interval is normalised to ``[lo, hi]`` with
    ``lo = LEAST(cumuld, cumulf)``, ``hi = GREATEST(cumuld, cumulf)`` so the
    test is robust to rows where the end is stored before the start. Two
    intervals overlap when ``GREATEST(lo1, lo2) < LEAST(hi1, hi2)`` (strict, so
    touching at a single point is not flagged).
    """
    ids = {k: sql.Identifier(v) for k, v in
           {"schema": schema, "table": table, "id": id_col, "axe": axe_col,
            "cumuld": cumuld_col, "cumulf": cumulf_col}.items()}
    return sql.SQL(
        """
        SELECT t1.{id}     AS id1,
               t2.{id}     AS id2,
               t1.{axe}    AS axe,
               {date_select}
               t1.{cumuld} AS t1_cumuld,
               t1.{cumulf} AS t1_cumulf,
               t2.{cumuld} AS t2_cumuld,
               t2.{cumulf} AS t2_cumulf,
               GREATEST(LEAST(t1.{cumuld}, t1.{cumulf}),
                        LEAST(t2.{cumuld}, t2.{cumulf}))  AS overlap_start,
               LEAST(GREATEST(t1.{cumuld}, t1.{cumulf}),
                     GREATEST(t2.{cumuld}, t2.{cumulf}))  AS overlap_end
        FROM {schema}.{table} t1
        JOIN {schema}.{table} t2
          ON t1.{axe} = t2.{axe}
         AND t1.{id} < t2.{id}
        WHERE GREATEST(LEAST(t1.{cumuld}, t1.{cumulf}),
                       LEAST(t2.{cumuld}, t2.{cumulf}))
            < LEAST(GREATEST(t1.{cumuld}, t1.{cumulf}),
                    GREATEST(t2.{cumuld}, t2.{cumulf}))
        ORDER BY t1.{axe}, t1.{id}, t2.{id}
        """
    ).format(date_select=_date_select(date_col), **ids)


def _pair_cols(r) -> dict:
    """Per-segment attributes shared by both queries: the four cumul endpoints,
    plus the date columns when the query selected them."""
    cols = {"axe": r["axe"], "id1": r["id1"], "id2": r["id2"],
            "t1_cumuld": r["t1_cumuld"], "t1_cumulf": r["t1_cumulf"],
            "t2_cumuld": r["t2_cumuld"], "t2_cumulf": r["t2_cumulf"]}
    if "t1_date" in r:
        cols["t1_date"] = r["t1_date"]
        cols["t2_date"] = r["t2_date"]
    return cols


def run_geometry(cur, query: sql.Composed, min_overlap: float) -> list[dict]:
    cur.execute(query, {"min_overlap": min_overlap})
    return [
        {**_pair_cols(r),
         "geom_overlap_length": round(float(r["overlap_length"]), 3)}
        for r in cur.fetchall()
    ]


def run_cumul(cur, query: sql.Composed) -> list[dict]:
    cur.execute(query)
    rows = []
    for r in cur.fetchall():
        start, end = r["overlap_start"], r["overlap_end"]
        rows.append({**_pair_cols(r),
                     "cumul_overlap_start": start, "cumul_overlap_end": end,
                     "cumul_overlap_length": end - start})
    return rows


# Columns describing the pair itself (not the per-analysis overlap result),
# carried over from whichever query first reports the pair.
_CARRY_COLS = ("t1_date", "t2_date",
               "t1_cumuld", "t1_cumulf", "t2_cumuld", "t2_cumulf")


def merge_pairs(
    geom_rows: list[dict], cumul_rows: list[dict], fieldnames: list[str]
) -> list[dict]:
    """Merge the geometry and cumul hits into one row per ``(axe, id1, id2)``.

    ``overlap_type`` becomes "geometry", "accumulated distance", or "both"
    depending on which analyses reported the pair.
    """
    pairs: dict[tuple, dict] = {}

    def slot(row: dict) -> dict:
        key = (row["axe"], row["id1"], row["id2"])
        if key not in pairs:
            pairs[key] = {f: "" for f in fieldnames}
            pairs[key].update(
                axe=row["axe"], id1=row["id1"], id2=row["id2"],
                _geom=False, _cumul=False)
            for c in _CARRY_COLS:
                if c in row:
                    pairs[key][c] = row[c]
        return pairs[key]

    for r in geom_rows:
        s = slot(r)
        s["_geom"] = True
        s["geom_overlap_length"] = r["geom_overlap_length"]
    for r in cumul_rows:
        s = slot(r)
        s["_cumul"] = True
        s["cumul_overlap_start"] = r["cumul_overlap_start"]
        s["cumul_overlap_end"] = r["cumul_overlap_end"]
        s["cumul_overlap_length"] = r["cumul_overlap_length"]

    for s in pairs.values():
        if s["_geom"] and s["_cumul"]:
            s["overlap_type"] = "both"
        elif s["_geom"]:
            s["overlap_type"] = "geometry"
        else:
            s["overlap_type"] = "accumulated distance"
        del s["_geom"], s["_cumul"]

    return sorted(pairs.values(), key=lambda s: (s["axe"], s["id1"], s["id2"]))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(
    path: Path, source: str, rows: list[dict], min_overlap: float,
    run_type: str, fieldnames: list[str],
) -> None:
    n_geom = sum(1 for r in rows if r["overlap_type"] == "geometry")
    n_cumul = sum(1 for r in rows if r["overlap_type"] == "accumulated distance")
    n_both = sum(1 for r in rows if r["overlap_type"] == "both")

    out = [
        f"# Overlapping analysis — `{source}`",
        "",
        f"- Analysis type: `{run_type}`",
        f"- Geometry threshold (`--min-overlap`): **{min_overlap} m**",
        f"- Overlapping pairs: **{len(rows)}** "
        f"(geometry only: {n_geom}, accumulated distance only: {n_cumul}, "
        f"both: {n_both})",
        "",
    ]
    if rows:
        out.append("| " + " | ".join(fieldnames) + " |")
        out.append("|" + "|".join(["---"] * len(fieldnames)) + "|")
        for r in rows:
            out.append("| " + " | ".join(str(r[f]) for f in fieldnames) + " |")
        out.append("")
    else:
        out += ["_No overlapping pairs found._", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml"
    )
    parser.add_argument(
        "--source", required=True,
        help="Source layer as 'schema.table' (e.g. client.20250916_trafic).",
    )
    parser.add_argument("--axe-col", default="axe")
    parser.add_argument("--cumuld-col", default="cumuld")
    parser.add_argument("--cumulf-col", default="cumulf")
    parser.add_argument("--geom-col", default="geom")
    parser.add_argument("--id-col", default="id")
    parser.add_argument(
        "--date-col", default=None,
        help="Optional date column (e.g. 'annee'). When given, t1_date and "
             "t2_date are added to the output files.",
    )
    parser.add_argument(
        "--type", choices=("geometry", "cumul", "both"), default="both",
        help="Which overlap analysis to run (default: both).",
    )
    parser.add_argument(
        "--min-overlap", type=float, default=1.0,
        help="Geometry overlap threshold in metres (default: 1.0).",
    )
    parser.add_argument(
        "--output", type=Path,
        default=PROJECT_ROOT / "overlapping_report.csv",
        help="Output CSV path; a sibling .md report is written alongside it.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the SQL that would run and exit without touching the DB.",
    )
    args = parser.parse_args(argv)

    schema, table = parse_source(args.source)
    cfg = load_config(args.config)

    do_geom = args.type in ("geometry", "both")
    do_cumul = args.type in ("cumul", "both")
    fieldnames = build_fieldnames(with_date=bool(args.date_col))

    geom_query = build_geometry_query(
        schema, table, args.id_col, args.axe_col, args.geom_col,
        args.cumuld_col, args.cumulf_col, args.date_col,
    ) if do_geom else None
    cumul_query = build_cumul_query(
        schema, table, args.id_col, args.axe_col, args.cumuld_col,
        args.cumulf_col, args.date_col,
    ) if do_cumul else None

    if args.dry_run:
        conn = connect(cfg)
        try:
            with conn.cursor() as cur:
                if geom_query is not None:
                    print("-- geometry overlap --", file=sys.stderr)
                    print(geom_query.as_string(cur), file=sys.stderr)
                if cumul_query is not None:
                    print("-- cumul overlap --", file=sys.stderr)
                    print(cumul_query.as_string(cur), file=sys.stderr)
        finally:
            conn.close()
        return 0

    print(
        f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
        file=sys.stderr,
    )
    print(
        f"Analysing overlaps in {schema}.{table} (type={args.type}, "
        f"min_overlap={args.min_overlap} m)...",
        file=sys.stderr,
    )

    geom_rows: list[dict] = []
    cumul_rows: list[dict] = []
    conn = connect(cfg)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if geom_query is not None:
                geom_rows = run_geometry(cur, geom_query, args.min_overlap)
                print(f"  geometry overlaps: {len(geom_rows)}", file=sys.stderr)
            if cumul_query is not None:
                cumul_rows = run_cumul(cur, cumul_query)
                print(f"  cumul overlaps:    {len(cumul_rows)}", file=sys.stderr)
    finally:
        conn.close()

    rows = merge_pairs(geom_rows, cumul_rows, fieldnames)
    print(
        f"  merged pairs:      {len(rows)} "
        f"({sum(1 for r in rows if r['overlap_type'] == 'both')} in both)",
        file=sys.stderr,
    )

    csv_path = args.output
    md_path = args.output.with_suffix(".md")
    write_csv(csv_path, rows, fieldnames)
    write_markdown(md_path, args.source, rows, args.min_overlap, args.type, fieldnames)

    print(
        f"Wrote {csv_path} ({len(rows)} rows) and {md_path}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
