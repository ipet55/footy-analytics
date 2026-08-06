alter table core.match_team_stat
  -- attacking detail
  add column shots_outside_box  smallint,
  add column shots_woodwork     smallint,
  add column big_chances        smallint,
  add column big_chances_missed smallint,
  add column key_passes         smallint,
  add column touches_in_box     smallint,
  add column crosses            smallint,
  add column crosses_accurate   smallint,
  add column dribbles_attempted smallint,
  add column dribbles_completed smallint,

  -- defensive detail
  add column blocks_made        smallint,
  add column clearances         smallint,
  add column duels_total        smallint,
  add column duels_won          smallint,
  add column aerials_won        smallint,
  add column errors_leading_to_shot smallint,

  -- discipline and set pieces
  add column fouls_drawn        smallint,
  add column second_yellow_cards smallint,
  add column penalties_awarded  smallint,
  add column penalties_scored   smallint,
  add column penalties_missed   smallint,
  add column own_goals          smallint,
  add column free_kicks         smallint,
  add column throw_ins          smallint,
  add column goal_kicks         smallint,

  -- possession quality (FBref)
  add column progressive_passes smallint,
  add column progressive_carries smallint,
  add column passes_final_third smallint,

  -- derived / modelling
  add column expected_points    numeric(4,3),

  -- long-tail provider-specific stats that are not worth a column
  add column extra              jsonb;

comment on column core.match_team_stat.shots_blocked is 'This team''s shots that the OPPONENT blocked (attacking metric).';
comment on column core.match_team_stat.blocks_made  is 'Opponent shots that THIS team blocked (defensive metric). Deliberately distinct from shots_blocked.';
comment on column core.match_team_stat.fouls_drawn  is 'Fouls suffered. Pairs with fouls_committed for referee and cards modelling.';
comment on column core.match_team_stat.extra        is 'Provider-specific stats with no dedicated column. Promote to a real column once you actually model on it.';

create index mts_extra_gin on core.match_team_stat using gin (extra);

-- ============================================================
-- Which source can actually supply which stat. Prevents the
-- pipeline from expecting possession from a CSV that has none.
-- ============================================================
create table core.stat_coverage (
  source_id     smallint not null references core.source,
  stat_column   text     not null,
  from_season   smallint,
  note          text,
  primary key (source_id, stat_column)
);

insert into core.stat_coverage (source_id, stat_column, from_season, note)
select s.source_id, v.col, v.from_season, v.note
from (values
    ('football_data_uk','shots',            1995, 'HS / AS'),
    ('football_data_uk','shots_on_target',  1995, 'HST / AST'),
    ('football_data_uk','corners',          1995, 'HC / AC'),
    ('football_data_uk','fouls_committed',  1995, 'HF / AF'),
    ('football_data_uk','yellow_cards',     1995, 'HY / AY'),
    ('football_data_uk','red_cards',        1995, 'HR / AR'),
    ('football_data_uk','shots_woodwork',   1995, 'HHW / AHW, older seasons only'),
    ('understat','xg',                      2014, 'per-team match xG'),
    ('understat','npxg',                    2014, 'non-penalty xG'),
    ('understat','deep_completions',        2014, 'passes completed within 20m of goal'),
    ('understat','ppda',                    2014, 'pressing intensity'),
    ('fbref','possession_pct',              2017, 'big-5 leagues, advanced stats era'),
    ('fbref','passes',                      2017, null),
    ('fbref','progressive_passes',          2017, null),
    ('fbref','progressive_carries',         2017, null),
    ('api_football','possession_pct',       2010, 'one request per fixture'),
    ('api_football','passes',               2010, null),
    ('api_football','blocks_made',          2010, null),
    ('api_football','saves',                2010, null),
    ('api_football','big_chances',          2010, 'coverage varies by league')
  ) as v(source_code, col, from_season, note)
join core.source s on s.code = v.source_code;

comment on table core.stat_coverage is 'Documents which provider supplies which stat and from when, so ingestion can assert expected coverage instead of silently writing nulls.';
