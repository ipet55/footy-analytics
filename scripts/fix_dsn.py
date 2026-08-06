#!/usr/bin/env python
"""Find a working Supabase connection endpoint and write it into .env.

The direct host (db.<ref>.supabase.co) is IPv6-only, so it stops resolving the
moment the machine loses IPv6 connectivity. The session pooler is IPv4 and works
everywhere, but its regional hostname prefix varies per project, so this probes
the candidates rather than guessing. The password is read from the existing .env
and never printed.
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import psycopg
from dotenv import load_dotenv

from footy.config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"
REF = "wziypmmboifdudvhhlmj"
REGION = "eu-west-1"


def candidates(password: str) -> list[tuple[str, str]]:
    pooled = [
        (f"session pooler {prefix}", f"postgresql://postgres.{REF}:{password}@{prefix}-{REGION}.pooler.supabase.com:5432/postgres")
        for prefix in ("aws-0", "aws-1")
    ]
    direct = [("direct (IPv6 only)", f"postgresql://postgres:{password}@db.{REF}.supabase.co:5432/postgres")]
    # Pooler first: it is IPv4 and survives losing IPv6.
    return pooled + direct


def main() -> int:
    load_dotenv(ENV_PATH)
    current = os.environ.get("DATABASE_URL", "")
    if not current:
        print("DATABASE_URL is empty; nothing to repair.")
        return 1

    authority = current.split("://", 1)[1].split("@")[0]
    password = authority.partition(":")[2]

    for label, dsn in candidates(password):
        host = urlsplit(dsn).hostname
        try:
            with psycopg.connect(dsn, connect_timeout=10) as conn, conn.cursor() as cur:
                cur.execute("select 1")
        except Exception as exc:  # noqa: BLE001 - we want to report and try the next one
            print(f"  {label:<26} {host}\n      -> {type(exc).__name__}: {str(exc).strip().splitlines()[0][:90]}")
            continue

        print(f"\nWorking endpoint: {label} ({host})")
        text = ENV_PATH.read_text()
        lines = [
            f"DATABASE_URL={dsn}" if line.startswith("DATABASE_URL=") else line
            for line in text.splitlines()
        ]
        ENV_PATH.write_text("\n".join(lines) + "\n")
        print("Updated .env")
        return 0

    print("\nNo endpoint worked.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
