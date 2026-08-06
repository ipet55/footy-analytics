from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

from footy.config import database_url


@contextmanager
def connect(autocommit: bool = False):
    with psycopg.connect(database_url(), autocommit=autocommit) as conn:
        yield conn


def fetch_all(conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None) -> tuple | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def copy_into_temp(
    conn: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    ddl: str,
) -> int:
    """Create a temp table from `ddl` and stream `rows` into it with COPY.

    Bulk loading goes through a temp table so the real insert can be a single
    idempotent INSERT ... ON CONFLICT statement rather than tens of thousands
    of round trips.
    """
    with conn.cursor() as cur:
        cur.execute(f"drop table if exists {table}")
        cur.execute(ddl)

        buf = io.StringIO()
        writer = csv.writer(buf)
        count = 0
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            count += 1
        buf.seek(0)

        collist = ", ".join(columns)
        with cur.copy(
            f"copy {table} ({collist}) from stdin with (format csv, null '')"
        ) as copy:
            copy.write(buf.read())
    return count


def start_run(conn: psycopg.Connection, source_code: str, entity: str, params: dict) -> int:
    row = fetch_one(
        conn,
        """
        insert into raw.ingest_run (source_id, entity, params)
        select source_id, %s, %s::jsonb from core.source where code = %s
        returning run_id
        """,
        (entity, json.dumps(params), source_code),
    )
    if row is None:
        raise RuntimeError(f"Unknown source code {source_code!r} in core.source")
    return row[0]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    rows_read: int | None = None,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update raw.ingest_run
               set status = %s, rows_read = %s, rows_written = %s,
                   error = %s, finished_at = now()
             where run_id = %s
            """,
            (status, rows_read, rows_written, error, run_id),
        )
