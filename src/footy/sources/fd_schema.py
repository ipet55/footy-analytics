"""Column maps for football-data.co.uk.

The file layout changed several times between 2014 and 2025 — Betbrain aggregates
(`BbAvH`) were replaced by `AvgH` in 2019/20, closing odds only exist for Pinnacle
before 2019, and bookmakers come and go. Every mapping here is therefore treated as
optional: a column is used when present and skipped when not.
"""

from __future__ import annotations

from typing import NamedTuple

# core.match_team_stat column -> (home column, away column)
TEAM_STATS: dict[str, tuple[str, str]] = {
    "shots": ("HS", "AS"),
    "shots_on_target": ("HST", "AST"),
    "corners": ("HC", "AC"),
    "fouls_committed": ("HF", "AF"),
    "yellow_cards": ("HY", "AY"),
    "red_cards": ("HR", "AR"),
    "offsides": ("HO", "AO"),
    "shots_woodwork": ("HHW", "AHW"),
}

# Stats that are exactly the opponent's value, so they are derived rather than read.
MIRRORED_STATS: dict[str, str] = {"fouls_drawn": "fouls_committed"}


class Book(NamedTuple):
    name: str
    # 1X2 column prefixes; the suffixes H/D/A are appended.
    open_prefix: str | None
    close_prefix: str | None
    is_aggregate: bool = False


# Ordered by how much weight they deserve: Pinnacle first, it is the sharpest and
# the only book with closing prices for all 12 seasons.
BOOKS_1X2: list[Book] = [
    Book("Pinnacle", "PS", "PSC"),
    Book("Bet365", "B365", "B365C"),
    Book("bwin", "BW", "BWC"),
    Book("William Hill", "WH", "WHC"),
    Book("VC Bet", "VC", "VCC"),
    Book("Interwetten", "IW", "IWC"),
    Book("Ladbrokes", "LB", "LBC"),
    Book("Stan James", "SJ", "SJC"),
    Book("Betfair Exchange", "BFE", "BFEC"),
    Book("Betfair Sportsbook", "BF", "BFC"),
    Book("Betfair Sportsbook", "BFD", "BFDC"),
    Book("1xBet", "1XB", "1XBC"),
    Book("BetMGM", "BMGM", "BMGMC"),
    Book("BetVictor", "BV", "BVC"),
    Book("Coolbet", "CL", "CLC"),
    # Site-computed consensus across all books it tracks. Flagged as aggregates so
    # they never contaminate an average taken over real bookmakers.
    Book("_average", "BbAv", None, True),
    Book("_maximum", "BbMx", None, True),
    Book("_average", "Avg", "AvgC", True),
    Book("_maximum", "Max", "MaxC", True),
]

# Over/Under 2.5 goals. (bookmaker, over column, under column, snapshot, is_aggregate)
OVER_UNDER_25: list[tuple[str, str, str, str, bool]] = [
    ("Pinnacle", "P>2.5", "P<2.5", "opening", False),
    ("Pinnacle", "PC>2.5", "PC<2.5", "closing", False),
    ("Bet365", "B365>2.5", "B365<2.5", "opening", False),
    ("Bet365", "B365C>2.5", "B365C<2.5", "closing", False),
    ("Betfair Exchange", "BFE>2.5", "BFE<2.5", "opening", False),
    ("Betfair Exchange", "BFEC>2.5", "BFEC<2.5", "closing", False),
    ("_average", "BbAv>2.5", "BbAv<2.5", "opening", True),
    ("_maximum", "BbMx>2.5", "BbMx<2.5", "opening", True),
    ("_average", "Avg>2.5", "Avg<2.5", "opening", True),
    ("_maximum", "Max>2.5", "Max<2.5", "opening", True),
    ("_average", "AvgC>2.5", "AvgC<2.5", "closing", True),
    ("_maximum", "MaxC>2.5", "MaxC<2.5", "closing", True),
]

# Asian handicap. The line itself moves between open and close, hence two line columns.
AH_LINE_OPEN = ("AHh", "BbAHh")
AH_LINE_CLOSE = ("AHCh",)

# (bookmaker, home column, away column, snapshot, is_aggregate)
ASIAN_HANDICAP: list[tuple[str, str, str, str, bool]] = [
    ("Pinnacle", "PAHH", "PAHA", "opening", False),
    ("Pinnacle", "PCAHH", "PCAHA", "closing", False),
    ("Bet365", "B365AHH", "B365AHA", "opening", False),
    ("Bet365", "B365CAHH", "B365CAHA", "closing", False),
    ("Betfair Exchange", "BFEAHH", "BFEAHA", "opening", False),
    ("Betfair Exchange", "BFECAHH", "BFECAHA", "closing", False),
    ("_average", "BbAvAHH", "BbAvAHA", "opening", True),
    ("_maximum", "BbMxAHH", "BbMxAHA", "opening", True),
    ("_average", "AvgAHH", "AvgAHA", "opening", True),
    ("_maximum", "MaxAHH", "MaxAHA", "opening", True),
    ("_average", "AvgCAHH", "AvgCAHA", "closing", True),
    ("_maximum", "MaxCAHH", "MaxCAHA", "closing", True),
]
