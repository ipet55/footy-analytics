-- ============================================================
-- The model registry and the predictions it produces.
--
-- Three things this schema is built to make impossible.
--
-- A prediction that cannot be reproduced. Every probability
-- points at the exact fit that produced it, including its
-- parameters and the window it was trained on, and at the
-- recalibration applied on top. A published percentage is the
-- output of a model *and* its calibration; storing only the
-- first would leave the number unexplainable.
--
-- A market being published before it has earned it. Phase 1
-- found that corner totals carry no signal while corner counts
-- do, and that cards are not yet accurate enough to show. That
-- verdict lives in ml.market.status, so the app filters on the
-- database rather than on somebody remembering.
--
-- Silent retraining. Refitting writes a new ml.model row rather
-- than updating one, so a model's history is auditable and an
-- old prediction still resolves to the version that made it.
-- ============================================================

-- ============================================================
-- What can be predicted at all.
--
-- Markets are registered rather than passed around as strings,
-- so a typo is a foreign key violation instead of a row nobody
-- notices. `stat` and `scope` together say what to measure, and
-- are what the settlement view joins on.
-- ============================================================
create table ml.market (
  market_code text primary key,
  stat        text not null,
  scope       text not null,
  kind        text not null,
  status      text not null,
  notes       text,
  constraint market_stat_check
    check (stat = any (array['goals', 'corners', 'cards', 'fouls', 'shots'])),
  constraint market_scope_check
    check (scope = any (array['match', 'home', 'away'])),
  constraint market_kind_check
    check (kind = any (array['over_under', 'outcome', 'btts'])),
  -- shipping: validated, safe to publish. held: real signal, but the
  -- percentages are not accurate enough for a user to act on.
  -- rejected: measured and found to carry no signal; kept so the
  -- finding is not rediscovered.
  constraint market_status_check
    check (status = any (array['shipping', 'held', 'rejected']))
);

comment on table ml.market is 'Registry of predictable markets. status encodes whether a market has earned the right to be published, so the app can filter on the database rather than on convention.';
comment on column ml.market.status is 'shipping = validated walk-forward in every league. held = ranks fixtures well but percentages not yet publishable. rejected = no signal found; recorded so it is not tried again by accident.';
comment on column ml.market.scope is 'match = both teams combined, home/away = one side only. Corners are the case that matters: the match total carries no signal while each side''s count does.';

insert into ml.market (market_code, stat, scope, kind, status, notes) values
  ('goals_1x2',      'goals',   'match', 'outcome',    'shipping',
   'Dixon-Coles. Log-loss 0.98583 against Pinnacle closing 0.96031 in the Premier League.'),
  ('goals_total',    'goals',   'match', 'over_under', 'shipping',  null),
  ('goals_home',     'goals',   'home',  'over_under', 'shipping',  null),
  ('goals_away',     'goals',   'away',  'over_under', 'shipping',  null),
  ('goals_btts',     'goals',   'match', 'btts',       'shipping',  null),
  ('fouls_total',    'fouls',   'match', 'over_under', 'shipping',
   'Strongest count market: beats a rolling benchmark by 5.4-6.5% in all five leagues.'),
  ('corners_home',   'corners', 'home',  'over_under', 'shipping',
   'Beats the benchmark by 2.1-6.3%. Dominance moves corners between sides, so the side matters and the total does not.'),
  ('corners_away',   'corners', 'away',  'over_under', 'shipping',
   'Beats the benchmark by 1.9-3.9%.'),
  ('shots_total',    'shots',   'match', 'over_under', 'shipping',
   'Thin but consistent edge, 0.8-4.5%.'),
  ('cards_total',    'cards',   'match', 'over_under', 'held',
   'Real but small. Referees are only recorded for the Premier League, and the two leagues calibrating worst are both leagues without them.'),
  ('cards_home',     'cards',   'home',  'over_under', 'held', null),
  ('cards_away',     'cards',   'away',  'over_under', 'held', null),
  ('shots_home',     'shots',   'home',  'over_under', 'held',
   'Ranks well (4.4-7.6%) but reliability reaches 14%, so the percentages are not publishable yet.'),
  ('shots_away',     'shots',   'away',  'over_under', 'held', null),
  ('fouls_home',     'fouls',   'home',  'over_under', 'held', null),
  ('fouls_away',     'fouls',   'away',  'over_under', 'held', null),
  ('corners_total',  'corners', 'match', 'over_under', 'rejected',
   'Measured at roughly zero gain and negative in three of five leagues. Dominance transfers corners between the sides rather than creating them, so the total barely varies with the fixture. Do not publish.');

-- ============================================================
-- One row per fit.
--
-- Refitting appends. A prediction made in September stays
-- attached to the September fit, which is the only way to ask
-- later whether the model was wrong or merely different.
--
-- `coefficients` holds the fitted parameters so a prediction can
-- be explained, and rebuilt, without refitting from scratch —
-- and so a claim about a team's attack strength can be traced to
-- a number rather than an intuition.
-- ============================================================
create table ml.model (
  model_id       bigserial primary key,
  code           text     not null,
  stat           text     not null,
  competition_id smallint not null references core.competition,
  params         jsonb    not null,
  coefficients   jsonb,
  trained_from   date     not null,
  trained_to     date     not null,
  n_matches      integer  not null,
  fitted_at      timestamptz not null default now(),
  notes          text,
  constraint model_code_check
    check (code = any (array['dixon_coles', 'count_total', 'count_team'])),
  constraint model_stat_check
    check (stat = any (array['goals', 'corners', 'cards', 'fouls', 'shots'])),
  -- The window must cover something. That trained_to is also the
  -- earliest kickoff this fit may predict is enforced on the
  -- predictions themselves, by trigger, since it needs the match.
  constraint model_window_check check (trained_to > trained_from),
  constraint model_matches_check check (n_matches > 0)
);

create index model_lookup_idx
  on ml.model (stat, competition_id, trained_to desc, fitted_at desc);

comment on table ml.model is 'One row per fit, never updated. An old prediction resolves to the exact version that produced it.';
comment on column ml.model.trained_to is 'Exclusive upper bound of the training window, and therefore the earliest kickoff this fit may predict. A fit must not be used on a match it learned from.';
comment on column ml.model.params is 'Hyperparameters, including the time decay xi. Without these the fit is not reproducible.';
comment on column ml.model.coefficients is 'Fitted parameters: per-team attack and defence or tempo, home advantage, dispersion, referee effects. Enough to predict without refitting, and to explain a prediction.';

-- ============================================================
-- The recalibration, stored per market and line.
--
-- Not an optional extra. Every count model is overconfident in
-- the same way — matches it calls 59% come in at 49% — and what
-- gets published is sigmoid(intercept + slope * logit(raw)).
-- A stored probability without its calibration is not a
-- reproducible number, so this table is part of the model, not
-- a diagnostic beside it.
--
-- slope < 1 compresses the spread toward the average, which is
-- the usual correction. slope = 1 with intercept = 0 is the
-- identity, written when there is not yet enough evidence to
-- correct anything.
-- ============================================================
create table ml.calibration (
  model_id       bigint  not null references ml.model on delete cascade,
  market_code    text    not null references ml.market,
  line           numeric(5,2),
  intercept      numeric(8,5) not null,
  slope          numeric(8,5) not null,
  n_observations integer not null,
  fitted_at      timestamptz not null default now(),
  -- A unique constraint rather than a primary key, because the line is
  -- genuinely absent for 1X2 and both-teams-to-score and a primary key
  -- cannot hold a null. `nulls not distinct` is what makes the absence
  -- itself unique, so those markets get one calibration row each rather
  -- than a new one per write.
  constraint calibration_key
    unique nulls not distinct (model_id, market_code, line),
  constraint calibration_slope_check check (slope >= 0),
  constraint calibration_observations_check check (n_observations >= 0)
);

comment on table ml.calibration is 'Per-market probability recalibration on the log-odds. Published = sigmoid(intercept + slope * logit(raw)).';
comment on column ml.calibration.slope is 'Below 1 compresses the spread toward the average, correcting overconfidence. Exactly 1 with intercept 0 is the identity, used until enough predictions have been observed to fit anything.';
comment on column ml.calibration.n_observations is 'Predictions the correction was fitted on. Zero means the identity is in force.';

-- ============================================================
-- The predictions themselves.
--
-- Both probabilities are kept. p_calibrated is what a user is
-- shown; p_raw is what the model said before correction, and
-- keeping it is what allows the calibration to be re-examined
-- later without refitting everything.
-- ============================================================
create table ml.prediction (
  prediction_id bigserial primary key,
  match_id      bigint  not null references core.match on delete cascade,
  model_id      bigint  not null references ml.model on delete cascade,
  market_code   text    not null references ml.market,
  line          numeric(5,2),
  selection     text    not null,
  p_raw         numeric(7,6) not null,
  p_calibrated  numeric(7,6) not null,
  predicted_at  timestamptz not null default now(),
  constraint prediction_selection_check
    check (selection = any (array['over', 'home', 'draw', 'away', 'yes'])),
  constraint prediction_raw_range check (p_raw > 0 and p_raw < 1),
  constraint prediction_calibrated_range check (p_calibrated > 0 and p_calibrated < 1),
  -- An over/under needs a line and an outcome market must not have one.
  constraint prediction_line_presence check (
    (selection = 'over') = (line is not null)
  ),
  unique nulls not distinct (match_id, model_id, market_code, line, selection)
);

create index prediction_match_idx on ml.prediction (match_id, market_code);
create index prediction_model_idx on ml.prediction (model_id);

comment on table ml.prediction is 'One row per match, model, market, line and selection. p_calibrated is what gets published; p_raw is kept so the calibration can be revisited without refitting.';
comment on column ml.prediction.line is 'Null for 1X2 and both-teams-to-score, which have no line. Uniqueness treats nulls as equal so a duplicate cannot slip in.';

-- ============================================================
-- The one invariant worth a trigger.
--
-- A model must never predict a match it was fitted on. That is
-- the mistake that produces a backtest which looks excellent and
-- a model that loses money, and it cannot be expressed as a
-- check constraint because it spans three tables: the kickoff
-- lives on the match and the training bound lives on the fit.
--
-- Enforced on write rather than audited afterwards, because a
-- leaked prediction that has already been published has already
-- done its damage.
-- ============================================================
create function ml.assert_prediction_is_out_of_sample() returns trigger
language plpgsql as $$
declare
  kickoff date;
  bound   date;
begin
  select m.kickoff_date into kickoff from core.match m where m.match_id = new.match_id;
  select md.trained_to  into bound   from ml.model md where md.model_id = new.model_id;

  -- trained_to is exclusive, so a kickoff on the bound itself is fine.
  if kickoff < bound then
    raise exception
      'match % kicked off on % but model % was trained through %, so the match is inside its training window',
      new.match_id, kickoff, new.model_id, bound
      using errcode = 'check_violation',
            hint = 'Fit a model whose trained_to is on or before this kickoff, or predict a later match.';
  end if;

  return new;
end $$;

create trigger prediction_out_of_sample
  before insert or update of match_id, model_id on ml.prediction
  for each row execute function ml.assert_prediction_is_out_of_sample();

comment on function ml.assert_prediction_is_out_of_sample() is 'Refuses any prediction whose match falls inside its model''s training window. Spans three tables, so it cannot be a check constraint.';

-- ============================================================
-- What actually happened, in the same shape as a prediction.
--
-- Derived rather than stored. Realised results already live in
-- core, and a second copy would be one more thing that can
-- disagree with the first. The settlement rules for each market
-- therefore live here, in one place, instead of being
-- reimplemented by every query that wants to score something.
-- ============================================================
create view ml.observation as
select m.match_id,
       'goals'::text as stat,
       'match'::text as scope,
       (m.home_goals_ft + m.away_goals_ft)::numeric as value
  from core.match m
 where m.home_goals_ft is not null
union all
select m.match_id, 'goals', 'home', m.home_goals_ft::numeric
  from core.match m where m.home_goals_ft is not null
union all
select m.match_id, 'goals', 'away', m.away_goals_ft::numeric
  from core.match m where m.away_goals_ft is not null
union all
-- Per-team counts, and the match total as their sum. The sum is
-- taken here rather than trusted from anywhere else so the total
-- and the two sides can never disagree.
select tm.match_id, s.stat, 'match',
       sum(case s.stat
             when 'corners' then tm.corners_for
             when 'cards'   then tm.yellows_for + tm.reds_for
             when 'fouls'   then tm.fouls_committed
             when 'shots'   then tm.shots_for
           end)::numeric
  from core.team_match tm
 cross join (values ('corners'), ('cards'), ('fouls'), ('shots')) as s(stat)
 where tm.period = 'FT'
 group by tm.match_id, s.stat
having count(*) = 2 and bool_and(
         case s.stat
           when 'corners' then tm.corners_for
           when 'cards'   then tm.yellows_for + tm.reds_for
           when 'fouls'   then tm.fouls_committed
           when 'shots'   then tm.shots_for
         end is not null)
union all
select tm.match_id, s.stat,
       case when tm.is_home then 'home' else 'away' end,
       (case s.stat
          when 'corners' then tm.corners_for
          when 'cards'   then tm.yellows_for + tm.reds_for
          when 'fouls'   then tm.fouls_committed
          when 'shots'   then tm.shots_for
        end)::numeric
  from core.team_match tm
 cross join (values ('corners'), ('cards'), ('fouls'), ('shots')) as s(stat)
 where tm.period = 'FT'
   and (case s.stat
          when 'corners' then tm.corners_for
          when 'cards'   then tm.yellows_for + tm.reds_for
          when 'fouls'   then tm.fouls_committed
          when 'shots'   then tm.shots_for
        end) is not null;

comment on view ml.observation is 'Realised value per match, statistic and scope, derived from core so it cannot drift from the results themselves. The one place settlement is defined.';

-- ============================================================
-- Predictions joined to what happened.
--
-- `hit` is what every score, calibration check and reliability
-- table is computed from, so the comparison is made once here
-- rather than reinvented per query. Unplayed fixtures come back
-- with hit = null, which is how upcoming predictions stay
-- visible without being counted.
-- ============================================================
create view ml.prediction_scored as
select p.prediction_id,
       p.match_id,
       p.model_id,
       p.market_code,
       p.line,
       p.selection,
       p.p_raw,
       p.p_calibrated,
       p.predicted_at,
       mk.stat,
       mk.scope,
       mk.status,
       m.competition_id,
       m.season_id,
       m.kickoff_date,
       o.value as observed,
       case
         when o.value is null then null
         when mk.kind = 'over_under' then o.value > p.line
         when mk.kind = 'btts' then m.home_goals_ft > 0 and m.away_goals_ft > 0
         when mk.kind = 'outcome' then p.selection = case
                when m.home_goals_ft > m.away_goals_ft then 'home'
                when m.home_goals_ft = m.away_goals_ft then 'draw'
                else 'away'
              end
       end as hit
  from ml.prediction p
  join ml.market mk on mk.market_code = p.market_code
  join core.match m on m.match_id = p.match_id
  left join ml.observation o
         on o.match_id = p.match_id and o.stat = mk.stat and o.scope = mk.scope;

comment on view ml.prediction_scored is 'Every prediction next to whether it happened. hit is null for fixtures not yet played, so upcoming predictions appear without polluting any score.';
