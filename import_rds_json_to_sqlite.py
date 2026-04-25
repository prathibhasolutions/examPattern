#!/usr/bin/env python3
"""
Import a raw RDS export JSON into local SQLite.

Expected input format:
{
  "meta": {...},
  "tables": {
    "table_name": {
      "row_count": N,
      "columns": [...],
      "rows": [{...}, {...}]
    }
  }
}

This script only touches local SQLite. It never connects to RDS.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_EXCLUDED_TABLES = {
    "django_migrations",
}

# Columns added after the RDS export was made — supply defaults so NOT NULL constraints
# are satisfied when those columns are absent from the export rows.
TABLE_COLUMN_DEFAULTS: dict[str, dict[str, object]] = {
    "attempts_testattempt": {
        "evaluation_state": "not_started",
        "evaluation_error": "",
        "evaluation_started_at": None,
        "evaluation_finished_at": None,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import rds_export.json into a local SQLite database"
    )
    parser.add_argument(
        "--input",
        default="rds_export.json",
        help="Path to export JSON file (default: rds_export.json)",
    )
    parser.add_argument(
        "--sqlite",
        default="db.sqlite3",
        help="Path to SQLite DB file (default: db.sqlite3)",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete existing rows from matched tables before import",
    )
    parser.add_argument(
        "--include-migrations",
        action="store_true",
        help="Also import django_migrations table",
    )
    return parser.parse_args()


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("Invalid export file: missing top-level 'tables' object")
    if not isinstance(payload["tables"], dict):
        raise ValueError("Invalid export file: 'tables' must be an object")
    return payload


def get_sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return {row[0] for row in cur.fetchall()}


def wipe_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"DELETE FROM {quote_ident(table)}")


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0

    first = rows[0]
    if not isinstance(first, dict):
        raise ValueError(f"Rows for table {table} must be objects")

    # Merge any column defaults for columns absent from the export rows
    col_defaults = TABLE_COLUMN_DEFAULTS.get(table, {})
    extra_cols = [c for c in col_defaults if c not in first]

    columns = list(first.keys()) + extra_cols
    placeholders = ", ".join(["?"] * len(columns))
    col_sql = ", ".join(quote_ident(c) for c in columns)
    sql = f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders})"

    values = []
    for row in rows:
        converted = []
        for col in columns:
            if col in row:
                value = row[col]
            else:
                value = col_defaults.get(col)
            if isinstance(value, (dict, list)):
                converted.append(json.dumps(value, ensure_ascii=False))
            else:
                converted.append(value)
        values.append(tuple(converted))

    conn.executemany(sql, values)
    return len(values)


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    sqlite_path = Path(args.sqlite)

    try:
        payload = load_json(input_path)
    except Exception as exc:
        print(f"Failed to read input JSON: {exc}", file=sys.stderr)
        return 1

    tables_data: dict = payload.get("tables", {})

    if not sqlite_path.exists():
        print(
            f"SQLite file not found: {sqlite_path}. Run migrations first (python manage.py migrate).",
            file=sys.stderr,
        )
        return 1

    excluded = set(DEFAULT_EXCLUDED_TABLES)
    if args.include_migrations:
        excluded.clear()

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row

    imported_total = 0
    skipped_missing = []
    skipped_excluded = []

    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")

        sqlite_tables = get_sqlite_tables(conn)

        target_tables = [name for name in sorted(tables_data.keys()) if name in sqlite_tables]

        if args.wipe:
            for table in target_tables:
                if table in excluded:
                    skipped_excluded.append(table)
                    continue
                wipe_table(conn, table)

        for table in sorted(tables_data.keys()):
            if table in excluded:
                if table not in skipped_excluded:
                    skipped_excluded.append(table)
                continue

            table_info = tables_data.get(table, {})
            rows = table_info.get("rows", []) if isinstance(table_info, dict) else []

            if table not in sqlite_tables:
                skipped_missing.append(table)
                continue

            count = insert_rows(conn, table, rows)
            imported_total += count
            print(f"Imported {table}: {count} rows")

        # ── Clean up any FK violations that came from the production DB ──────
        # The production server may have orphaned rows (e.g. from direct SQL deletes
        # that bypassed Django's cascade).  Detect and delete them before committing
        # so that Django's migrate / check_constraints never sees them.
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        # Each row: (table, rowid, parent_table, fkid)
        if violations:
            from collections import defaultdict
            rowids_by_table: dict[str, list] = defaultdict(list)
            for row in violations:
                rowids_by_table[row[0]].append(row[1])
            for table, rowids in rowids_by_table.items():
                placeholders = ",".join("?" * len(rowids))
                conn.execute(
                    f"DELETE FROM {quote_ident(table)} WHERE rowid IN ({placeholders})",
                    rowids,
                )
                print(f"  Cleaned {len(rowids)} orphaned row(s) from {table}")
            print(f"  Total orphans removed: {sum(len(v) for v in rowids_by_table.values())}")
        else:
            print("  FK check: no violations found.")
        # ─────────────────────────────────────────────────────────────────────

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

        print("\nImport complete.")
        print(f"Total rows imported: {imported_total}")
        if skipped_excluded:
            print(f"Excluded tables: {', '.join(sorted(skipped_excluded))}")
        if skipped_missing:
            print(f"Tables not found in SQLite schema (skipped): {', '.join(sorted(skipped_missing))}")

        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
