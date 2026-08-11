"""Canonical team names for the identity layer.

football-data.co.uk uses terse names ("Man United", "Ath Bilbao", "M'gladbach").
This module maps them to full canonical names, which become `core.team.canonical_name`
with the source spelling registered in `core.team_alias`.

Deliberately, only football-data.co.uk aliases are registered here. Guessing at
Understat's or FBref's spellings would risk a *wrong* alias, which corrupts joins
silently. A *missing* alias surfaces loudly in `core.unresolved_alias`, so each new
source gets its names harvested from the source itself and reviewed.
"""

from __future__ import annotations

COMPETITION_COUNTRY = {
    "ENG-PL": "England",
    "ESP-LL": "Spain",
    "ITA-SA": "Italy",
    "GER-BL": "Germany",
    "FRA-L1": "France",
}

# football-data.co.uk name -> canonical name. Names absent here are already canonical.
CANONICAL_NAME: dict[str, str] = {
    # England
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Cardiff": "Cardiff City",
    "Huddersfield": "Huddersfield Town",
    "Hull": "Hull City",
    "Ipswich": "Ipswich Town",
    "Leeds": "Leeds United",
    "Leicester": "Leicester City",
    "Luton": "Luton Town",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle": "Newcastle United",
    "Norwich": "Norwich City",
    "Nott'm Forest": "Nottingham Forest",
    "QPR": "Queens Park Rangers",
    "Stoke": "Stoke City",
    "Swansea": "Swansea City",
    "Tottenham": "Tottenham Hotspur",
    "West Brom": "West Bromwich Albion",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    # Spain
    "Alaves": "Deportivo Alaves",
    "Almeria": "UD Almeria",
    "Ath Bilbao": "Athletic Club",
    "Ath Madrid": "Atletico Madrid",
    "Barcelona": "FC Barcelona",
    "Betis": "Real Betis",
    "Cadiz": "Cadiz CF",
    "Celta": "Celta Vigo",
    "Cordoba": "Cordoba CF",
    "Eibar": "SD Eibar",
    "Elche": "Elche CF",
    "Espanol": "Espanyol",
    "Getafe": "Getafe CF",
    "Girona": "Girona FC",
    "Granada": "Granada CF",
    "Huesca": "SD Huesca",
    "La Coruna": "Deportivo La Coruna",
    "Las Palmas": "UD Las Palmas",
    "Leganes": "CD Leganes",
    "Levante": "Levante UD",
    "Malaga": "Malaga CF",
    "Mallorca": "RCD Mallorca",
    "Osasuna": "CA Osasuna",
    "Oviedo": "Real Oviedo",
    "Sevilla": "Sevilla FC",
    "Sociedad": "Real Sociedad",
    "Sp Gijon": "Sporting Gijon",
    "Valencia": "Valencia CF",
    "Valladolid": "Real Valladolid",
    "Vallecano": "Rayo Vallecano",
    "Villarreal": "Villarreal CF",
    # Italy
    "Inter": "Inter Milan",
    "Milan": "AC Milan",
    "Roma": "AS Roma",
    "Verona": "Hellas Verona",
    "Spal": "SPAL",
    "Spezia": "Spezia Calcio",
    # Germany
    "Bielefeld": "Arminia Bielefeld",
    "Bochum": "VfL Bochum",
    "Darmstadt": "Darmstadt 98",
    "Dortmund": "Borussia Dortmund",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "FC Koln": "FC Koln",
    "Fortuna Dusseldorf": "Fortuna Dusseldorf",
    "Greuther Furth": "Greuther Furth",
    "Hamburg": "Hamburger SV",
    "Hannover": "Hannover 96",
    "Hertha": "Hertha Berlin",
    "Leverkusen": "Bayer Leverkusen",
    "M'gladbach": "Borussia Monchengladbach",
    "Mainz": "Mainz 05",
    "Nurnberg": "Nurnberg",
    "St Pauli": "St. Pauli",
    "Stuttgart": "VfB Stuttgart",
    "Wolfsburg": "VfL Wolfsburg",
    # France
    "Ajaccio": "AC Ajaccio",
    "Ajaccio GFCO": "GFC Ajaccio",
    "Bastia": "SC Bastia",
    "Le Havre": "Le Havre AC",
    "Lyon": "Olympique Lyonnais",
    "Marseille": "Olympique de Marseille",
    "Paris SG": "Paris Saint-Germain",
    "St Etienne": "Saint-Etienne",
}

# Short display name for compact UI, where the canonical name is unwieldy.
SHORT_NAME: dict[str, str] = {
    "Brighton & Hove Albion": "Brighton",
    "Wolverhampton Wanderers": "Wolves",
    "Tottenham Hotspur": "Tottenham",
    "West Bromwich Albion": "West Brom",
    "Manchester United": "Man Utd",
    "Manchester City": "Man City",
    "Queens Park Rangers": "QPR",
    "Nottingham Forest": "Nott'm Forest",
    "Borussia Monchengladbach": "M'gladbach",
    "Borussia Dortmund": "Dortmund",
    "Eintracht Frankfurt": "Frankfurt",
    "Bayer Leverkusen": "Leverkusen",
    "Paris Saint-Germain": "PSG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "Atletico Madrid": "Atletico",
    "Athletic Club": "Ath Bilbao",
    "Deportivo La Coruna": "Deportivo",
    "FC Barcelona": "Barcelona",
    "Rayo Vallecano": "Rayo",
}


# Understat names that resolve neither to a canonical name nor to a spelling
# football-data.co.uk already registered. Most of its 167 names matched
# automatically; these are the remainder, and each is unambiguous. Several are
# German clubs where Understat writes the umlaut as "ue" — norm_name strips
# accents but does not transliterate, so "Fuerth" and "Furth" do not collide.
UNDERSTAT_ALIASES: dict[str, str] = {
    "Clermont Foot": "Clermont",
    "Borussia M.Gladbach": "Borussia Monchengladbach",
    "FC Cologne": "FC Koln",
    "FC Heidenheim": "Heidenheim",
    "Fortuna Duesseldorf": "Fortuna Dusseldorf",
    "Greuther Fuerth": "Greuther Furth",
    "Nuernberg": "Nurnberg",
    "RasenBallsport Leipzig": "RB Leipzig",
    "Parma Calcio 1913": "Parma",
    "SPAL 2013": "SPAL",
}


# FBref name -> canonical name, for spellings neither an exact match nor another
# source's registered alias resolves. FBref is also inconsistent with itself —
# its schedule says "Manchester Utd" where its team sheets say "Manchester
# United" — but both of those resolve on their own, so only genuine gaps go here.
#
# Harvest these with `footy check-lineup-names` rather than guessing. Every entry
# below was reported by that command or by a scrape that refused to continue.
FBREF_ALIASES: dict[str, str] = {
    # England
    "Nottingham": "Nottingham Forest",
    # Italy — the schedule says "Inter", the team sheets say "Internazionale".
    "Internazionale": "Inter Milan",
    # Spain
    "Dep. La Coruña": "Deportivo La Coruna",
    # Germany
    "Arminia": "Arminia Bielefeld",
    "Hertha BSC": "Hertha Berlin",
    "Mönchengladbach": "Borussia Monchengladbach",
    "Düsseldorf": "Fortuna Dusseldorf",
    "Paderborn 07": "Paderborn",
    # norm_name strips the umlaut but does not add the "FC" our canonical has.
    "Köln": "FC Koln",
    # France
    "PSG": "Paris Saint-Germain",
    "Evian": "Evian Thonon Gaillard",
    # Gazélec is GFC Ajaccio, not the older AC Ajaccio, and both are in the data.
    "Gazélec Ajaccio": "GFC Ajaccio",
}


# Clubs FBref lists on a league's page that were never in that league. The
# Bundesliga relegation play-off is two legs against the third-placed second
# division club, so it appears in the schedule while belonging to no top flight
# season we store — FBref lists 308 Bundesliga matches for 2024-25 where the
# league itself played 306.
#
# These are declared rather than skipped quietly. An unresolvable name is
# normally the symptom of a missing alias, which silently drops matches, so the
# loaders stop when they meet one. Naming the exceptions keeps that alarm
# working instead of weakening it.
FBREF_NOT_IN_LEAGUE: frozenset[str] = frozenset({
    "Elversberg",  # 2. Bundesliga; 2024-25 play-off against Heidenheim
    "Karlsruher",  # 2014-15 play-off against Hamburg
    "BTSV",        # Eintracht Braunschweig; 2016-17 play-off against Wolfsburg
})


# ClubElo tracks exactly the same 167 top-flight clubs; 151 matched automatically
# through a canonical name or an alias another source had already registered.
# These 16 use short forms or German "ue" transliteration.
CLUBELO_ALIASES: dict[str, str] = {
    "Forest": "Nottingham Forest",
    "Evian TG": "Evian Thonon Gaillard",
    "Gazelec": "GFC Ajaccio",
    "Bayern": "Bayern Munich",
    "Duesseldorf": "Fortuna Dusseldorf",
    "Frankfurt": "Eintracht Frankfurt",
    "Fuerth": "Greuther Furth",
    "Gladbach": "Borussia Monchengladbach",
    "Holstein": "Holstein Kiel",
    "Koeln": "FC Koln",
    "Schalke": "Schalke 04",
    "Werder": "Werder Bremen",
    "Atletico": "Atletico Madrid",
    "Bilbao": "Athletic Club",
    "Depor": "Deportivo La Coruna",
    "Gijon": "Sporting Gijon",
}


def canonical(source_name: str) -> str:
    return CANONICAL_NAME.get(source_name.strip(), source_name.strip())


def short(canonical_name: str) -> str | None:
    return SHORT_NAME.get(canonical_name)
