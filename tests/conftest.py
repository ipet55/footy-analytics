from __future__ import annotations

import pytest

from footy import config, db


@pytest.fixture(scope="session")
def conn():
    if not config.has_database_url():
        pytest.skip("DATABASE_URL is not set")
    with db.connect() as connection:
        yield connection


@pytest.fixture
def scalar(conn):
    """Run a query expected to return a single count, usually of violations."""

    def run(sql: str, params=None):
        return db.fetch_one(conn, sql, params)[0]

    return run
