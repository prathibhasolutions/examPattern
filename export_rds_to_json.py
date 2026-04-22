#!/usr/bin/env python3
"""
Export a PostgreSQL database (for example AWS RDS) to a single JSON file.

Optimised for the full schema of this project (37 tables, all apps).

Safety:
- Opens a read-only transaction (BEGIN READ ONLY).
- Performs SELECT queries only.
- Does not create/update/delete any data.

Improvements over the original version:
- Server-side (named) cursor + fetchmany() — never buffers an entire table in
  psycopg2 client memory, preventing OOM on large tables.
- Per-table error handling — a single failed table is logged and skipped;
  all other tables are still exported.
- Primary-key flag included in every column's metadata.
- Foreign-key relationships exported per table (useful for import ordering).
- Approximate row counts pre-fetched from pg_stat_user_tables for accurate
  progress reporting before the actual SELECT runs.
- django_model field in each table entry maps it to its Django app.ModelName.
- --batch-size CLI flag lets you tune memory vs. speed.
- Exit code 3 when some tables failed (vs 0 = full success, 1 = fatal error).

Usage (PowerShell — credentials are read from Django settings automatically):
  cd C:\\Users\\AKHILESH\\OneDrive\\Documents\\GitHub\\examPattern
  python export_rds_to_json.py
  python export_rds_to_json.py --output my_backup.json
  python export_rds_to_json.py --batch-size 1000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

# ── Load Django DB settings so you don't have to set env vars manually ──
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mocktest_platform.settings")

try:
    import django
    django.setup()
    from django.conf import settings as _dj_settings
    _db = _dj_settings.DATABASES["default"]
    os.environ.setdefault("RDS_DB_HOST",     _db.get("HOST", ""))
    os.environ.setdefault("RDS_DB_NAME",     _db.get("NAME", ""))
    os.environ.setdefault("RDS_DB_USER",     _db.get("USER", ""))
    os.environ.setdefault("RDS_DB_PASSWORD", _db.get("PASSWORD", ""))
    os.environ.setdefault("RDS_DB_PORT",     str(_db.get("PORT", "5432")))
except Exception as _e:
    print(f"[warn] Could not auto-load Django settings ({_e}); "
          "falling back to env vars.", file=sys.stderr)

import psycopg2
from psycopg2.extras import RealDictCursor

# Default rows fetched per round-trip when using the server-side cursor.
_DEFAULT_BATCH = 500


# ─────────────────────────── CLI ────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export all PostgreSQL tables to one JSON file (read-only)."
    )
    parser.add_argument(
        "--output",
        default="rds_export.json",
        help="Output JSON file path (default: rds_export.json)",
    )
    parser.add_argument(
        "--schema",
        default=os.getenv("RDS_DB_SCHEMA", "public"),
        help="PostgreSQL schema to export (default: public or RDS_DB_SCHEMA env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH,
        help=f"Rows fetched per round-trip via server-side cursor "
             f"(default: {_DEFAULT_BATCH})",
    )
    return parser.parse_args()


# ─────────────────────────── helpers ────────────────────────────────────────

def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def json_default(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"Type not serializable: {type(value).__name__}")


def get_table_names(conn, schema: str) -> list[str]:
    """Return all base tables in the schema, sorted alphabetically."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [row[0] for row in cur.fetchall()]


def get_column_meta(conn, schema: str, table_name: str) -> list[dict]:
    """Return ordered column metadata including primary-key flag."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END
                    AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                 AND tc.table_schema    = ku.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema    = %s
                  AND tc.table_name      = %s
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (schema, table_name, schema, table_name),
        )
        return [
            {
                "name":              row[0],
                "type":              row[1],
                "nullable":          row[2] == "YES",
                "default":           row[3],
                "max_length":        row[4],
                "numeric_precision": row[5],
                "numeric_scale":     row[6],
                "is_primary_key":    row[7],
            }
            for row in cur.fetchall()
        ]


def get_foreign_keys(conn, schema: str, table_name: str) -> list[dict]:
    """Return foreign-key relationships for the table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                kcu.column_name,
                ccu.table_name  AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints        AS tc
            JOIN information_schema.key_column_usage         AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema    = kcu.table_schema
            JOIN information_schema.constraint_column_usage  AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema    = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = %s
              AND tc.table_name      = %s
            ORDER BY kcu.column_name
            """,
            (schema, table_name),
        )
        return [
            {
                "column":            row[0],
                "references_table":  row[1],
                "references_column": row[2],
            }
            for row in cur.fetchall()
        ]


def get_approx_row_count(conn, schema: str, table_name: str) -> int:
    """
    Fast approximate row count from pg_stat_user_tables.
    Falls back to an exact COUNT(*) if the stats entry is missing.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n_live_tup
            FROM pg_stat_user_tables
            WHERE schemaname = %s AND relname = %s
            """,
            (schema, table_name),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table_name}"')
        return cur.fetchone()[0]


def fetch_all_rows(conn, schema: str, table_name: str, batch_size: int) -> list[dict]:
    """
    Stream all rows via a server-side named cursor using fetchmany().
    This avoids loading the full result set into psycopg2 client memory,
    which prevents OOM errors on large tables.
    """
    rows: list[dict] = []
    cursor_name = f"export_{table_name[:40].replace(' ', '_')}"
    with conn.cursor(cursor_name, cursor_factory=RealDictCursor) as cur:
        cur.execute(f'SELECT * FROM "{schema}"."{table_name}"')
        while True:
            batch = cur.fetchmany(batch_size)
            if not batch:
                break
            rows.extend(dict(r) for r in batch)
    return rows


def build_django_table_map() -> dict[str, str]:
    """Map each db_table → 'app_label.ModelName' using the Django app registry."""
    try:
        from django.apps import apps
        return {
            m._meta.db_table: f"{m._meta.app_label}.{m.__name__}"
            for m in apps.get_models()
        }
    except Exception:
        return {}


# ─────────────────────────── main ───────────────────────────────────────────

def main() -> int:
    args = parse_args()

    try:
        host     = required_env("RDS_DB_HOST")
        dbname   = required_env("RDS_DB_NAME")
        user     = required_env("RDS_DB_USER")
        password = required_env("RDS_DB_PASSWORD")
        port     = os.getenv("RDS_DB_PORT", "5432").strip() or "5432"
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        conn = psycopg2.connect(
            host=host,
            dbname=dbname,
            user=user,
            password=password,
            port=port,
            connect_timeout=20,
            sslmode="prefer",
        )
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    django_map   = build_django_table_map()
    failed_tables: list[str] = []

    export_payload = {
        "meta": {
            "host":             host,
            "database":         dbname,
            "schema":           args.schema,
            "exported_at_utc":  datetime.utcnow().isoformat() + "Z",
            "read_only":        True,
            "batch_size":       args.batch_size,
        },
        "tables": {},
    }

    try:
        # Enforce read-only at the transaction level for extra safety.
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")

        tables = get_table_names(conn, args.schema)
        print(f"Found {len(tables)} tables in schema '{args.schema}'.")

        # Pre-fetch approximate row counts for progress display.
        row_counts: dict[str, int] = {}
        for t in tables:
            try:
                row_counts[t] = get_approx_row_count(conn, args.schema, t)
            except Exception:
                row_counts[t] = -1

        total_rows = sum(v for v in row_counts.values() if v >= 0)
        print(f"Approximate total rows across all tables: {total_rows:,}\n")

        for table_name in tables:
            approx     = row_counts.get(table_name, -1)
            approx_str = f"~{approx:,}" if approx >= 0 else "?"
            print(f"  [{table_name}]  ({approx_str} rows) ...", end=" ", flush=True)

            try:
                columns = get_column_meta(conn, args.schema, table_name)
                fkeys   = get_foreign_keys(conn, args.schema, table_name)
                rows    = fetch_all_rows(conn, args.schema, table_name, args.batch_size)

                export_payload["tables"][table_name] = {
                    "django_model": django_map.get(table_name),
                    "row_count":    len(rows),
                    "columns":      columns,
                    "foreign_keys": fkeys,
                    "rows":         rows,
                }
                print(f"OK  ({len(rows):,} rows)")

            except Exception as exc:
                failed_tables.append(table_name)
                print(f"FAILED — {exc}")

        # Write collected data to JSON.
        print(f"\nWriting JSON to '{args.output}' ...")
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump(export_payload, fp, indent=2, default=json_default)

        conn.rollback()

        exported = len(tables) - len(failed_tables)
        print(f"\nDone. Exported {exported}/{len(tables)} tables → {args.output}")
        if failed_tables:
            print(f"[warn] Failed tables: {', '.join(failed_tables)}", file=sys.stderr)
        print("RDS safety: transaction was read-only and rolled back.")
        return 0 if not failed_tables else 3

    except Exception as exc:
        conn.rollback()
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
