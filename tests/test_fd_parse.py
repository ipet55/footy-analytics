"""Tests for the football-data.co.uk parser.

Only the stage rule is covered here, because it is the one piece of the parser
that infers something the source does not state. Everything else is a column
rename, which fails loudly at load time when it is wrong.

The rule matters more than it looks. It decides match identity: `stage` is part
of the natural key, so getting it wrong either collapses two real fixtures into
one row or splits one fixture across two.
"""

from __future__ import annotations

from footy.sources.fd_parse import ParsedSeason, _assign_stages


def season(*fixtures: tuple[str, str, str]) -> ParsedSeason:
    """Build a season from (date, home, away) triples, in any order."""
    out = ParsedSeason("TEST", 2024)
    out.matches = [
        {"row_id": i, "kickoff_date": day, "home_name": home, "away_name": away}
        for i, (day, home, away) in enumerate(fixtures)
    ]
    return out


def stages(parsed: ParsedSeason) -> list[str]:
    return [m["stage"] for m in sorted(parsed.matches, key=lambda m: m["row_id"])]


def test_a_double_round_robin_is_all_regular_season():
    """The reverse fixture is not a second meeting: home and away are different
    ordered pairs, and every league plays both."""
    s = season(
        ("2024-08-01", "Anderlecht", "Genk"),
        ("2024-12-01", "Genk", "Anderlecht"),
    )
    _assign_stages(s)
    assert stages(s) == ["regular", "regular"]


def test_a_repeated_pairing_is_the_phase_after_the_season():
    """Belgium's playoff replays fixtures that have already been played in the
    same order, which is the only thing that can produce a repeat."""
    s = season(
        ("2024-08-01", "Anderlecht", "Genk"),
        ("2024-12-01", "Genk", "Anderlecht"),
        ("2025-04-01", "Anderlecht", "Genk"),
    )
    _assign_stages(s)
    assert stages(s) == ["regular", "regular", "playoff"]


def test_the_earlier_meeting_is_the_regular_one_whatever_the_file_order():
    """The CSV is not reliably in date order, and taking it on trust would label
    the April fixture regular and the August one a playoff — inverting the
    season and silently changing which row each result lands on."""
    s = season(
        ("2025-04-01", "Anderlecht", "Genk"),
        ("2024-08-01", "Anderlecht", "Genk"),
    )
    _assign_stages(s)
    assert stages(s) == ["playoff", "regular"]


def test_three_meetings_leave_only_the_first_as_regular():
    """Guards the boundary rather than the format: no league we hold plays a
    pairing three times, so the rule should not quietly invent a third stage."""
    s = season(
        ("2024-08-01", "Anderlecht", "Genk"),
        ("2025-04-01", "Anderlecht", "Genk"),
        ("2025-05-01", "Anderlecht", "Genk"),
    )
    _assign_stages(s)
    assert stages(s) == ["regular", "playoff", "playoff"]


def test_two_clubs_meeting_on_one_day_do_not_collide_with_another_pair():
    """Same date, different pairings — the rule keys on the pair, not the day."""
    s = season(
        ("2024-08-01", "Anderlecht", "Genk"),
        ("2024-08-01", "Club Brugge", "Gent"),
        ("2024-08-01", "Genk", "Anderlecht"),
    )
    _assign_stages(s)
    assert stages(s) == ["regular", "regular", "regular"]
