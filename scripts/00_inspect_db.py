"""Inspect a PostgreSQL database and emit a Markdown structure report.

What it does
------------
- Reads connection info from ``config/config.yaml`` (key ``source``).
- Inspects exactly three schemas, read from config keys
  ``client_schema``, ``processing_schema``, ``reporting_schema``.
- For each schema, lists base tables only (skips views and any table owned by a
  PostgreSQL extension, such as PostGIS's ``spatial_ref_sys``).
- For every table and every column, includes a free-text **description** which
  is persisted in a sidecar YAML file (``db_descriptions.yaml``). That YAML is
  the editable source of truth — the markdown is regenerated from it on every
  run. Existing descriptions are never overwritten; new tables/columns appear
  with empty descriptions for the user to fill in. Tables/columns that no
  longer exist in the DB are moved under ``_orphans`` instead of being deleted.

Usage
-----
    python scripts/00_inspect_db.py
    python scripts/00_inspect_db.py --config config/config.yaml \
        --descriptions db_descriptions.yaml --output db_structure.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCHEMA_KEYS = ("client_schema", "processing_schema", "reporting_schema")


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not raw or "source" not in raw:
        raise ValueError(f"Config {path} is missing the 'source' section")
    src = raw["source"]
    missing = [k for k in SCHEMA_KEYS if k not in src]
    if missing:
        raise ValueError(
            f"Config 'source' is missing schema key(s): {', '.join(missing)}"
        )
    return src


def connect(cfg: dict[str, Any]):
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        dbname=cfg["database"],
    )


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

def schema_exists(cur, schema: str) -> bool:
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
    return cur.fetchone() is not None


def fetch_tables(cur, schema: str) -> list[dict[str, Any]]:
    """Return base / partitioned tables only, excluding extension-owned ones."""
    cur.execute(
        """
        SELECT c.relname                                  AS name,
               c.relkind                                  AS kind,
               c.reltuples::bigint                        AS row_estimate,
               pg_total_relation_size(c.oid)              AS total_bytes,
               obj_description(c.oid, 'pg_class')         AS comment
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.objid = c.oid
                AND d.deptype = 'e'
          )
        ORDER BY c.relname
        """,
        (schema,),
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_columns(cur, schema: str, table: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT a.attname                                          AS name,
               format_type(a.atttypid, a.atttypmod)               AS data_type,
               NOT a.attnotnull                                    AS nullable,
               pg_get_expr(d.adbin, d.adrelid)                    AS default,
               col_description(a.attrelid, a.attnum)              AS comment
        FROM pg_attribute a
        JOIN pg_class c     ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d
               ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname = %s
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_primary_key(cur, schema: str, table: str) -> list[str]:
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class c     ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
        WHERE n.nspname = %s
          AND c.relname = %s
          AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
        """,
        (schema, table),
    )
    return [r["attname"] for r in cur.fetchall()]


def fetch_foreign_keys(cur, schema: str, table: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT con.conname                                                  AS name,
               (SELECT array_agg(att.attname ORDER BY ord.ord)
                FROM unnest(con.conkey) WITH ORDINALITY ord(attnum, ord)
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid AND att.attnum = ord.attnum) AS columns,
               fn.nspname                                                    AS ref_schema,
               fc.relname                                                    AS ref_table,
               (SELECT array_agg(att.attname ORDER BY ord.ord)
                FROM unnest(con.confkey) WITH ORDINALITY ord(attnum, ord)
                JOIN pg_attribute att
                  ON att.attrelid = con.confrelid AND att.attnum = ord.attnum) AS ref_columns,
               con.confupdtype                                               AS on_update,
               con.confdeltype                                               AS on_delete
        FROM pg_constraint con
        JOIN pg_class c      ON c.oid = con.conrelid
        JOIN pg_namespace n  ON n.oid = c.relnamespace
        JOIN pg_class fc     ON fc.oid = con.confrelid
        JOIN pg_namespace fn ON fn.oid = fc.relnamespace
        WHERE n.nspname = %s
          AND c.relname = %s
          AND con.contype = 'f'
        ORDER BY con.conname
        """,
        (schema, table),
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_indexes(cur, schema: str, table: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT i.relname           AS name,
               ix.indisunique       AS is_unique,
               ix.indisprimary      AS is_primary,
               pg_get_indexdef(ix.indexrelid) AS definition
        FROM pg_index ix
        JOIN pg_class i     ON i.oid  = ix.indexrelid
        JOIN pg_class t     ON t.oid  = ix.indrelid
        JOIN pg_namespace n ON n.oid  = t.relnamespace
        WHERE n.nspname = %s
          AND t.relname = %s
        ORDER BY i.relname
        """,
        (schema, table),
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Descriptions sidecar
# ---------------------------------------------------------------------------
#
# Layout of db_descriptions.yaml:
#
#   <schema>:
#     <table_name>:
#       description: "free text"
#       columns:
#         <col_name>: "free text"
#   _orphans:
#     <schema>:
#       <table_name>: { ... same shape ... }

ORPHAN_KEY = "_orphans"
DATABASE_KEY = "_database"
RESERVED_KEYS = {ORPHAN_KEY, DATABASE_KEY}


def load_descriptions(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} should contain a YAML mapping at the top level")
    return data


def _empty_table_entry() -> dict[str, Any]:
    return {"description": "", "columns": {}}


def merge_descriptions(
    existing: dict[str, Any],
    live: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    """Merge the live structure into the user's descriptions file.

    ``live`` maps schema -> table_name -> list of column names.

    Behavior:
    - Live schemas/tables/columns appear in the merged result, preserving any
      existing description text.
    - Anything that exists in the YAML but no longer in the DB is moved under
      ``_orphans`` so the user's notes are never silently deleted.
    """
    merged: dict[str, Any] = {}

    # Preserve the global database description block as-is. If it doesn't exist
    # yet, seed an empty one so the user has somewhere to write.
    db_block = existing.get(DATABASE_KEY) or {}
    if not isinstance(db_block, dict):
        db_block = {}
    if "description" not in db_block:
        db_block["description"] = ""
    merged[DATABASE_KEY] = db_block

    orphans: dict[str, Any] = dict(existing.get(ORPHAN_KEY, {}))

    # Pass 1 — pull every live schema/table/column from existing into merged,
    # creating empty entries where the YAML had nothing yet.
    for schema, tables in live.items():
        schema_existing = existing.get(schema, {}) or {}
        merged_schema: dict[str, Any] = {}
        for tbl_name, col_names in tables.items():
            tbl_existing = schema_existing.get(tbl_name) or _empty_table_entry()
            # Normalize shape just in case the user removed a key by hand.
            if "description" not in tbl_existing:
                tbl_existing["description"] = ""
            if "columns" not in tbl_existing or not isinstance(
                tbl_existing["columns"], dict
            ):
                tbl_existing["columns"] = {}

            cols_existing = tbl_existing["columns"]
            cols_merged: dict[str, str] = {}
            for col in col_names:
                cols_merged[col] = cols_existing.get(col, "") or ""

            # Anything in cols_existing but not in col_names is an orphan column.
            orphan_cols = {
                c: v for c, v in cols_existing.items() if c not in col_names
            }
            if orphan_cols:
                orphans.setdefault(schema, {}).setdefault(tbl_name, {})
                orphans[schema][tbl_name].setdefault("columns", {})
                orphans[schema][tbl_name]["columns"].update(orphan_cols)

            merged_schema[tbl_name] = {
                "description": tbl_existing["description"] or "",
                "columns": cols_merged,
            }
        merged[schema] = merged_schema

        # Tables that exist in YAML but not in live -> orphan the whole table.
        for tbl_name, tbl_entry in schema_existing.items():
            if tbl_name not in tables:
                orphans.setdefault(schema, {})[tbl_name] = tbl_entry

    # Schemas that exist in YAML but not in live -> orphan the whole schema.
    for schema, tables in existing.items():
        if schema in RESERVED_KEYS:
            continue
        if schema not in live:
            orphans.setdefault(schema, {})
            if isinstance(tables, dict):
                orphans[schema].update(tables)

    if orphans:
        merged[ORPHAN_KEY] = orphans
    return merged


def write_descriptions(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(
            "# Edit this file to describe tables and columns.\n"
            "# Descriptions here are preserved across re-runs of 00_inspect_db.py.\n"
            "# `_orphans` holds entries for tables/columns no longer in the DB.\n"
            "\n"
        )
        yaml.safe_dump(
            data,
            fh,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

FK_ACTIONS = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


def fmt_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def md_escape(text: str | None) -> str:
    if text is None:
        return ""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build_report(
    cur,
    cfg: dict[str, Any],
    schemas: list[str],
    descriptions: dict[str, Any],
) -> tuple[str, dict[str, dict[str, list[str]]]]:
    """Render the markdown report and return ``(markdown, live)`` where ``live``
    is the schema -> table -> [columns] map used to refresh descriptions."""
    out: list[str] = []
    out.append(f"# Database structure — `{cfg['database']}`")
    out.append("")
    out.append(
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} from "
        f"`{cfg['host']}:{cfg['port']}` (user `{cfg['user']}`)._"
    )
    out.append("")
    cur.execute("SELECT version() AS v")
    out.append(f"- PostgreSQL: `{cur.fetchone()['v']}`")
    out.append(f"- Schemas inspected: {', '.join(f'`{s}`' for s in schemas)}")
    out.append(
        "- Edit `db_descriptions.yaml` to fill in descriptions. They are "
        "preserved on re-run."
    )
    out.append("")

    db_block = descriptions.get(DATABASE_KEY) or {}
    db_desc = (db_block.get("description") or "").strip()
    out.append("## About this database")
    out.append("")
    if db_desc:
        out.append(db_desc)
    else:
        out.append(
            "_Add a description of the database and its use case in_ "
            "`db_descriptions.yaml` _under the_ `_database:` _key. "
            "It will be preserved across re-runs._"
        )
    out.append("")

    # Pre-fetch tables for the overview + the live map.
    schema_tables: dict[str, list[dict[str, Any]]] = {}
    live: dict[str, dict[str, list[str]]] = {}
    for schema in schemas:
        if not schema_exists(cur, schema):
            schema_tables[schema] = []
            live[schema] = {}
            continue
        tables = fetch_tables(cur, schema)
        schema_tables[schema] = tables
        live[schema] = {}
        for t in tables:
            cols = fetch_columns(cur, schema, t["name"])
            live[schema][t["name"]] = [c["name"] for c in cols]
            t["_columns"] = cols  # cache for the detail pass

    # Overview
    out.append("## Overview")
    out.append("")
    out.append("| Schema | Exists | Tables |")
    out.append("|---|:---:|---:|")
    for schema in schemas:
        exists = schema in live and (
            schema_tables[schema] or schema_exists(cur, schema)
        )
        # schema_exists already cached above through the fetch
        out.append(
            f"| `{schema}` | {'YES' if schema_exists(cur, schema) else 'NO'} "
            f"| {len(schema_tables[schema])} |"
        )
    out.append("")

    # TOC
    out.append("## Contents")
    out.append("")
    for schema in schemas:
        out.append(f"- [`{schema}`](#schema-{schema.lower()})")
    out.append("")

    # Per-schema detail
    for schema in schemas:
        out.append(f"## Schema `{schema}` <a id=\"schema-{schema.lower()}\"></a>")
        out.append("")
        if not schema_exists(cur, schema):
            out.append("_Schema does not exist in the database._")
            out.append("")
            continue

        tables = schema_tables[schema]
        if not tables:
            out.append("_No tables._")
            out.append("")
            continue

        # Summary table
        out.append("| Table | Rows (est.) | Size | Description |")
        out.append("|---|---:|---:|---|")
        for t in tables:
            desc = (
                descriptions.get(schema, {})
                .get(t["name"], {})
                .get("description", "")
            )
            marker = " (partitioned)" if t["kind"] == "p" else ""
            out.append(
                f"| [`{t['name']}`](#tbl-{schema.lower()}-{t['name'].lower()})"
                f"{marker} "
                f"| {t['row_estimate']:,} "
                f"| {fmt_size(t['total_bytes'])} "
                f"| {md_escape(desc)} |"
            )
        out.append("")

        for t in tables:
            _emit_table_detail(out, cur, schema, t, descriptions)

    return "\n".join(out) + "\n", live


def _emit_table_detail(
    out: list[str],
    cur,
    schema: str,
    table: dict[str, Any],
    descriptions: dict[str, Any],
) -> None:
    name = table["name"]
    out.append(
        f"### `{schema}.{name}` <a id=\"tbl-{schema.lower()}-{name.lower()}\"></a>"
    )
    out.append("")

    tbl_desc = (
        descriptions.get(schema, {}).get(name, {}).get("description", "")
    )
    out.append(f"**Description:** {tbl_desc or '_(add via db_descriptions.yaml)_'}")
    out.append("")

    out.append(
        f"- Row estimate: **{table['row_estimate']:,}**  "
        f"- Size: **{fmt_size(table['total_bytes'])}**"
    )
    out.append("")

    cols = table.get("_columns") or fetch_columns(cur, schema, name)
    pk = set(fetch_primary_key(cur, schema, name))
    col_desc_map = (
        descriptions.get(schema, {}).get(name, {}).get("columns", {}) or {}
    )

    out.append("**Columns**")
    out.append("")
    out.append("| # | Column | Type | Nullable | Default | PK | Description |")
    out.append("|---:|---|---|:---:|---|:---:|---|")
    for idx, c in enumerate(cols, 1):
        col_desc = col_desc_map.get(c["name"], "") or ""
        out.append(
            f"| {idx} "
            f"| `{c['name']}` "
            f"| `{c['data_type']}` "
            f"| {'YES' if c['nullable'] else 'NO'} "
            f"| {md_escape(c['default']) if c['default'] else ''} "
            f"| {'PK' if c['name'] in pk else ''} "
            f"| {md_escape(col_desc)} |"
        )
    out.append("")

    fks = fetch_foreign_keys(cur, schema, name)
    if fks:
        out.append("**Foreign keys**")
        out.append("")
        out.append("| Name | Columns | References | On update | On delete |")
        out.append("|---|---|---|---|---|")
        for fk in fks:
            cols_str = ", ".join(f"`{c}`" for c in fk["columns"])
            ref_cols_str = ", ".join(f"`{c}`" for c in fk["ref_columns"])
            ref = f"`{fk['ref_schema']}.{fk['ref_table']}` ({ref_cols_str})"
            out.append(
                f"| `{fk['name']}` | {cols_str} | {ref} "
                f"| {FK_ACTIONS.get(fk['on_update'], fk['on_update'])} "
                f"| {FK_ACTIONS.get(fk['on_delete'], fk['on_delete'])} |"
            )
        out.append("")

    indexes = fetch_indexes(cur, schema, name)
    if indexes:
        out.append("**Indexes**")
        out.append("")
        out.append("| Name | Unique | Primary | Definition |")
        out.append("|---|:---:|:---:|---|")
        for ix in indexes:
            out.append(
                f"| `{ix['name']}` "
                f"| {'YES' if ix['is_unique'] else ''} "
                f"| {'YES' if ix['is_primary'] else ''} "
                f"| `{md_escape(ix['definition'])}` |"
            )
        out.append("")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config" / "config.yaml"
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "db_structure.md"
    )
    parser.add_argument(
        "--descriptions",
        type=Path,
        default=PROJECT_ROOT / "db_descriptions.yaml",
        help="Path to the sidecar YAML holding descriptions (preserved on re-run).",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    schemas = [cfg[k] for k in SCHEMA_KEYS]

    print(
        f"Connecting to {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}...",
        file=sys.stderr,
    )
    existing_descriptions = load_descriptions(args.descriptions)
    print(
        f"Loaded {args.descriptions} "
        f"({'new' if not existing_descriptions else 'existing'}).",
        file=sys.stderr,
    )

    conn = connect(cfg)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            print(
                f"Inspecting {len(schemas)} schema(s): {', '.join(schemas)}",
                file=sys.stderr,
            )
            report, live = build_report(cur, cfg, schemas, existing_descriptions)
    finally:
        conn.close()

    merged = merge_descriptions(existing_descriptions, live)
    write_descriptions(args.descriptions, merged)
    args.output.write_text(report, encoding="utf-8")
    print(
        f"Wrote {args.output} ({len(report):,} chars) and "
        f"{args.descriptions}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
