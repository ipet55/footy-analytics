"""Writing fits, calibrations and predictions into the ml schema.

Kept apart from the models themselves so that the modelling code never has to
know a database exists, and so the rules about what reaches the tables live in
one readable place.

Two of those rules are worth stating up front.

A refit is a new row, but the *same* fit is not. Re-running a prediction for a
date that has already been predicted must not manufacture a second model
version, because the fit is deterministic: identical training data and
hyperparameters give identical coefficients. So a fit is looked up before it is
inserted, and predictions upsert. Running twice is a no-op rather than a
duplicate history.

Nothing is published for a market the database has marked rejected. The
registry is the authority on that, not this module and not the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from footy import db


@dataclass(frozen=True)
class Market:
    code: str
    stat: str
    scope: str
    kind: str
    status: str


@dataclass(frozen=True)
class PredictionRow:
    match_id: int
    market_code: str
    line: float | None
    selection: str
    p_raw: float
    p_calibrated: float


def load_markets(conn: psycopg.Connection, include_rejected: bool = False) -> list[Market]:
    """The markets worth computing, straight from the registry.

    Rejected markets are excluded by default rather than filtered by the caller,
    so a market that has been measured and found useless cannot be revived by a
    forgetful command-line flag.
    """
    rows = db.fetch_all(
        conn,
        """
        select market_code, stat, scope, kind, status
          from ml.market
         where status <> 'rejected' or %s
         order by market_code
        """,
        (include_rejected,),
    )
    return [Market(*r) for r in rows]


def competition_id(conn: psycopg.Connection, code: str) -> int:
    row = db.fetch_one(
        conn, "select competition_id from core.competition where code = %s", (code,)
    )
    if row is None:
        raise RuntimeError(f"unknown competition {code!r}")
    return row[0]


def upsert_model(
    conn: psycopg.Connection,
    code: str,
    stat: str,
    competition_id: int,
    params: dict[str, Any],
    coefficients: dict[str, Any],
    trained_from: date,
    trained_to: date,
    n_matches: int,
    notes: str | None = None,
) -> int:
    """Return the id of this fit, reusing the row if it already exists.

    Identity is the training window plus the hyperparameters, not the
    coefficients: those are an output. If the same data and settings somehow
    produced different numbers we would want to know, so the coefficients are
    refreshed on a match rather than silently left stale.
    """
    existing = db.fetch_one(
        conn,
        """
        select model_id from ml.model
         where code = %s and stat = %s and competition_id = %s
           and params = %s::jsonb and trained_from = %s and trained_to = %s
           and n_matches = %s
         order by fitted_at desc
         limit 1
        """,
        (code, stat, competition_id, json.dumps(params, sort_keys=True),
         trained_from, trained_to, n_matches),
    )
    if existing is not None:
        with conn.cursor() as cur:
            cur.execute(
                "update ml.model set coefficients = %s::jsonb where model_id = %s",
                (json.dumps(coefficients), existing[0]),
            )
        return existing[0]

    row = db.fetch_one(
        conn,
        """
        insert into ml.model
          (code, stat, competition_id, params, coefficients,
           trained_from, trained_to, n_matches, notes)
        values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
        returning model_id
        """,
        (code, stat, competition_id, json.dumps(params, sort_keys=True),
         json.dumps(coefficients), trained_from, trained_to, n_matches, notes),
    )
    assert row is not None
    return row[0]


def upsert_calibration(
    conn: psycopg.Connection,
    model_id: int,
    market_code: str,
    line: float | None,
    intercept: float,
    slope: float,
    n_observations: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into ml.calibration
              (model_id, market_code, line, intercept, slope, n_observations)
            values (%s, %s, %s, %s, %s, %s)
            on conflict on constraint calibration_key do update
               set intercept = excluded.intercept,
                   slope = excluded.slope,
                   n_observations = excluded.n_observations,
                   fitted_at = now()
            """,
            (model_id, market_code, line, intercept, slope, n_observations),
        )


def upsert_predictions(
    conn: psycopg.Connection, model_id: int, rows: list[PredictionRow]
) -> int:
    """Write predictions, replacing any already held for the same fit.

    The database refuses a prediction whose match falls inside the model's
    training window, so a mistake here fails loudly instead of quietly
    publishing a number that knew the result.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into ml.prediction
              (match_id, model_id, market_code, line, selection, p_raw, p_calibrated)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (match_id, model_id, market_code, line, selection) do update
               set p_raw = excluded.p_raw,
                   p_calibrated = excluded.p_calibrated,
                   predicted_at = now()
            """,
            [
                (r.match_id, model_id, r.market_code, r.line, r.selection,
                 r.p_raw, r.p_calibrated)
                for r in rows
            ],
        )
    return len(rows)
