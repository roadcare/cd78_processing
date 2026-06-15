"""First processing step — copy raw tables from the original schema to the
processing schema (drop + recreate, preserving structure and indexes), then
ensure each copied table has ``id`` as PRIMARY KEY, then compute the
geometry-calibration columns on ``session`` / ``image``.

Reads ``config/config.yaml`` and copies each of ``session``, ``image``,
``road_data`` from ``source.original_schema`` to ``source.processing_schema`` in
the same PostgreSQL database. Existing target tables are replaced.

Per-table PK promotion policy (idempotent, runs in the same transaction as the
copy):
  - target already has PK on (id)          -> no-op
  - target has PK on other column(s)       -> kept as-is
  - target has no PK and has id NOT NULL   -> ADD PRIMARY KEY (id)
  - target has no PK and id is NULLABLE    -> SET NOT NULL then ADD PRIMARY KEY
  - target has no PK and no id column      -> ADD COLUMN id BIGINT IDENTITY +
                                              PRIMARY KEY

Geometry calibration (single transaction, only runs when both ``session`` and
``image`` are in --tables — see ``task/example_calculate_geoCalibration.md``):
  1. ``image."geomCalibration"`` = ST_MakePointM(X, Y, cumulStartSession)
  2. ``session.geom``            = ST_Simplify(LineString of ordered image.geom, 0.5)
  3. ``session."geomCalibration"`` = LineString of ordered image."geomCalibration"

Usage
-----
    python scripts/01_copy_source_tables.py
    python scripts/01_copy_source_tables.py --dry-run
    python scripts/01_copy_source_tables.py --tables session,image
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TABLES = ("session", "image", "road_data")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not raw or "source" not in raw:
        raise ValueError(f"Config {path} is missing the 'source' section")
    src = raw["source"]
    for key in ("host", "port", "user", "password", "database",
                "original_schema", "processing_schema"):
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


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r','p')
        """,
        (schema, table),
    )
    return cur.fetchone() is not None


def row_count(cur, schema: str, table: str) -> int:
    cur.execute(
        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
    )
    return cur.fetchone()[0]


def current_primary_key(cur, schema: str, table: str) -> list[str]:
    """Return the ordered column names of the table's PK, or [] if none."""
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class c     ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
        WHERE n.nspname = %s AND c.relname = %s AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
        """,
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def column_nullable(cur, schema: str, table: str, column: str) -> bool | None:
    """``True`` if column is nullable, ``False`` if NOT NULL, ``None`` if missing."""
    cur.execute(
        """
        SELECT NOT a.attnotnull
        FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        """,
        (schema, table, column),
    )
    row = cur.fetchone()
    return None if row is None else bool(row[0])


def ensure_id_primary_key(cur, schema: str, table: str) -> str:
    """Promote `id` to PRIMARY KEY on ``schema.table`` if appropriate.

    Rules (matches the agreed policy):
    - Existing PK on (id)              -> no-op, "kept: PK(id)"
    - Existing PK on other columns     -> no-op, "kept: PK(<cols>)"
    - No PK, id NOT NULL               -> ADD PRIMARY KEY (id)
    - No PK, id NULLABLE               -> SET NOT NULL on id, then ADD PRIMARY KEY (id)
    - No PK, no id column              -> ADD COLUMN id (identity) + PRIMARY KEY
    """
    pk_cols = current_primary_key(cur, schema, table)
    if pk_cols == ["id"]:
        return "kept: PK(id)"
    if pk_cols:
        return f"kept: PK({','.join(pk_cols)})"

    nullable = column_nullable(cur, schema, table, "id")
    if nullable is None:
        # No id column and no PK at all -> synthesize one.
        cur.execute(
            sql.SQL(
                "ALTER TABLE {}.{} "
                "ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
            ).format(sql.Identifier(schema), sql.Identifier(table))
        )
        return "added: synthetic id (BIGINT identity) + PK"

    if nullable:
        cur.execute(
            sql.SQL("ALTER TABLE {}.{} ALTER COLUMN id SET NOT NULL").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        )
        cur.execute(
            sql.SQL("ALTER TABLE {}.{} ADD PRIMARY KEY (id)").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        )
        return "added: PK(id) (forced NOT NULL)"

    cur.execute(
        sql.SQL("ALTER TABLE {}.{} ADD PRIMARY KEY (id)").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
    )
    return "added: PK(id)"


def copy_table(
    conn,
    src_schema: str,
    dst_schema: str,
    table: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Replace ``dst_schema.table`` with a fresh copy of ``src_schema.table``.

    Runs in a single transaction so a failure mid-copy leaves the target table
    in its previous state.
    """
    stmts = [
        sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(dst_schema), sql.Identifier(table)
        ),
        sql.SQL("CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)").format(
            sql.Identifier(dst_schema), sql.Identifier(table),
            sql.Identifier(src_schema), sql.Identifier(table),
        ),
        sql.SQL("INSERT INTO {}.{} SELECT * FROM {}.{}").format(
            sql.Identifier(dst_schema), sql.Identifier(table),
            sql.Identifier(src_schema), sql.Identifier(table),
        ),
        sql.SQL("ANALYZE {}.{}").format(
            sql.Identifier(dst_schema), sql.Identifier(table)
        ),
    ]

    if dry_run:
        with conn.cursor() as cur:
            rendered = [s.as_string(cur) for s in stmts]
        rendered.append(
            f"-- then: ensure_id_primary_key(public={dst_schema}, {table}) "
            f"-- adds PK(id) if the table lacks one"
        )
        return {"table": table, "dry_run": True, "sql": rendered}

    started = time.perf_counter()
    with conn:  # transaction
        with conn.cursor() as cur:
            src_count = row_count(cur, src_schema, table)
            for stmt in stmts:
                cur.execute(stmt)
            pk_status = ensure_id_primary_key(cur, dst_schema, table)
            dst_count = row_count(cur, dst_schema, table)
    elapsed = time.perf_counter() - started

    return {
        "table": table,
        "dry_run": False,
        "src_count": src_count,
        "dst_count": dst_count,
        "elapsed_s": elapsed,
        "match": src_count == dst_count,
        "pk_status": pk_status,
    }


GEOM_CALIBRATION_SQL = [
    # 1) Point-M per image: XY from image.geom, M from cumulStartSession.
    """
    UPDATE {schema}.image
       SET "geomCalibration" =
           ST_MakePointM(ST_X(geom), ST_Y(geom), "cumulStartSession"::numeric)
    """,
    # 2) Session.geom = simplified LineString built from ordered image geoms.
    """
    UPDATE {schema}.session t1
       SET geom = ST_Simplify(r2.newgeom, 0.5)
      FROM (
            SELECT "sessionId", ST_MakeLine(r1.geom) AS newgeom
              FROM (
                    SELECT "sessionId", "cumulStartSession", geom
                      FROM {schema}.image
                  ORDER BY "sessionId", "cumulStartSession"
                   ) r1
          GROUP BY r1."sessionId"
           ) r2
     WHERE r2."sessionId" = t1.id
    """,
    # 3) Session.geomCalibration = LineString from ordered image geomCalibrations.
    """
    UPDATE {schema}.session t1
       SET "geomCalibration" = r2.newgeom
      FROM (
            SELECT "sessionId", ST_MakeLine(r1."geomCalibration") AS newgeom
              FROM (
                    SELECT "sessionId", "cumulStartSession", "geomCalibration"
                      FROM {schema}.image
                  ORDER BY "sessionId", "cumulStartSession"
                   ) r1
          GROUP BY r1."sessionId"
           ) r2
     WHERE r2."sessionId" = t1.id
    """,
]

GEOM_CALIBRATION_REQUIRED_TABLES = ("session", "image")


def update_geom_calibration(
    conn,
    dst_schema: str,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the 3 geometry calibration UPDATEs in a single transaction.

    Sources the SQL from ``task/example_calculate_geoCalibration.md``:
    populates ``image."geomCalibration"`` as a Point-M, then rebuilds
    ``session.geom`` and ``session."geomCalibration"`` as LineStrings ordered
    by ``"cumulStartSession"``.
    """
    schema_id = sql.Identifier(dst_schema)
    stmts = [
        sql.SQL(template).format(schema=schema_id)
        for template in GEOM_CALIBRATION_SQL
    ]

    if dry_run:
        return {"dry_run": True, "sql": [s.as_string(conn) for s in stmts]}

    started = time.perf_counter()
    updated: list[int] = []
    with conn:  # transaction
        with conn.cursor() as cur:
            for stmt in stmts:
                cur.execute(stmt)
                updated.append(cur.rowcount)
    elapsed = time.perf_counter() - started

    return {
        "dry_run": False,
        "image_rows_updated": updated[0],
        "session_geom_rows_updated": updated[1],
        "session_geomcal_rows_updated": updated[2],
        "elapsed_s": elapsed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml"
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=",".join(DEFAULT_TABLES),
        help=f"Comma-separated table names (default: {','.join(DEFAULT_TABLES)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the SQL that would be executed and exit without changes.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    src_schema = cfg["original_schema"]
    dst_schema = cfg["processing_schema"]
    tables = [t.strip() for t in args.tables.split(",") if t.strip()]

    if src_schema == dst_schema:
        print(
            f"ERROR: original_schema and processing_schema are both '{src_schema}'. "
            "Refusing to copy a schema onto itself.",
            file=sys.stderr,
        )
        return 2

    print(
        f"DB: {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}",
        file=sys.stderr,
    )
    print(f"Copying {src_schema} -> {dst_schema}: {', '.join(tables)}", file=sys.stderr)
    if args.dry_run:
        print("DRY RUN — no changes will be made.", file=sys.stderr)

    conn = connect(cfg)
    conn.autocommit = False

    exit_code = 0
    try:
        # Pre-flight: confirm all source tables exist before mutating anything.
        with conn.cursor() as cur:
            missing = [t for t in tables if not table_exists(cur, src_schema, t)]
        if missing:
            print(
                f"ERROR: source table(s) missing in '{src_schema}': {', '.join(missing)}",
                file=sys.stderr,
            )
            return 3

        for table in tables:
            print(f"\n--- {dst_schema}.{table} ---", file=sys.stderr)
            result = copy_table(
                conn, src_schema, dst_schema, table, dry_run=args.dry_run
            )
            if result["dry_run"]:
                for s in result["sql"]:
                    print("  " + s + ";", file=sys.stderr)
                continue

            print(
                f"  src rows: {result['src_count']:,}  "
                f"dst rows: {result['dst_count']:,}  "
                f"PK: {result['pk_status']}  "
                f"({result['elapsed_s']:.2f}s)",
                file=sys.stderr,
            )
            if not result["match"]:
                print(
                    f"  WARNING: row count mismatch for {table}",
                    file=sys.stderr,
                )
                exit_code = 1

        # Post-copy geometry calibration — requires both session and image.
        missing_for_geocal = [
            t for t in GEOM_CALIBRATION_REQUIRED_TABLES if t not in tables
        ]
        print("\n--- geometry calibration ---", file=sys.stderr)
        if missing_for_geocal:
            print(
                f"  SKIPPED: requires {','.join(GEOM_CALIBRATION_REQUIRED_TABLES)}; "
                f"not in --tables (missing: {','.join(missing_for_geocal)}).",
                file=sys.stderr,
            )
        else:
            geocal = update_geom_calibration(conn, dst_schema, dry_run=args.dry_run)
            if geocal["dry_run"]:
                for s in geocal["sql"]:
                    print("  " + s.strip() + ";", file=sys.stderr)
            else:
                print(
                    f"  image.geomCalibration       updated: "
                    f"{geocal['image_rows_updated']:,}",
                    file=sys.stderr,
                )
                print(
                    f"  session.geom                updated: "
                    f"{geocal['session_geom_rows_updated']:,}",
                    file=sys.stderr,
                )
                print(
                    f"  session.geomCalibration     updated: "
                    f"{geocal['session_geomcal_rows_updated']:,}  "
                    f"({geocal['elapsed_s']:.2f}s)",
                    file=sys.stderr,
                )
    finally:
        conn.close()

    print("\nDone.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
