#!/usr/bin/env python
"""Export applied Supabase migrations into sql/ so the schema is version controlled.

Migrations are applied through the Supabase MCP connection, which records them in
supabase_migrations.schema_migrations. This pulls them back out as files.
"""

from __future__ import annotations

import sys

from footy import db
from footy.config import PROJECT_ROOT

OUT_DIR = PROJECT_ROOT / "sql" / "migrations"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            select version, coalesce(name, 'unnamed'), statements
              from supabase_migrations.schema_migrations
             order by version
            """,
        )

    for version, name, statements in rows:
        path = OUT_DIR / f"{version}_{name}.sql"
        body = ";\n\n".join(s.strip().rstrip(";") for s in (statements or []) if s.strip())
        path.write_text(body + ";\n" if body else "")
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")

    print(f"\n{len(rows)} migrations exported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
