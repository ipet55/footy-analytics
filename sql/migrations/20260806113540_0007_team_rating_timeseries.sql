-- ============================================================
-- Team strength over time.
--
-- Stored as validity ranges rather than one row per day, which is
-- how ClubElo publishes it: a rating holds until the club next
-- plays. Looking up "strength on the morning of this match" is
-- then a range containment test, and - importantly - it is
-- point-in-time correct by construction, because valid_from is
-- the date the rating became known.
-- ============================================================
create table core.team_rating (
  team_id     integer  not null references core.team on delete cascade,
  source_id   smallint not null references core.source,
  valid_from  date     not null,
  valid_to    date     not null,
  rating      numeric(8,3) not null,
  rank        integer,
  level       smallint,
  primary key (team_id, source_id, valid_from),
  constraint team_rating_range check (valid_to >= valid_from)
);

create index team_rating_lookup_idx on core.team_rating (team_id, source_id, valid_from desc);

comment on table core.team_rating is 'Elo-style strength ratings as validity ranges. A rating applies from valid_from through valid_to inclusive.';
comment on column core.team_rating.valid_from is 'First date this rating applied. Safe to use as an as-of key: a rating with valid_from <= kickoff was knowable before kickoff.';

-- ============================================================
-- Pre-match rating for both sides, and the differential, which is
-- the single most useful form of the feature.
-- ============================================================
create view core.match_rating as
select m.match_id,
       m.kickoff_date,
       hr.rating as home_rating,
       ar.rating as away_rating,
       hr.rating - ar.rating as rating_diff,
       -- Standard Elo expectation, before any home-advantage adjustment.
       round((1.0 / (1 + power(10, (ar.rating - hr.rating) / 400.0)))::numeric, 5) as elo_p_home
  from core.match m
  left join core.team_rating hr
         on hr.team_id = m.home_team_id
        and m.kickoff_date between hr.valid_from and hr.valid_to
  left join core.team_rating ar
         on ar.team_id = m.away_team_id
        and m.kickoff_date between ar.valid_from and ar.valid_to;

comment on view core.match_rating is 'Ratings in force on the day of each match. elo_p_home ignores home advantage and draws, so it is a feature to feed a model, not a prediction on its own.';
