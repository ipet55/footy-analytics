-- ============================================================
-- Record how absences moved a fixture's probabilities.
--
-- The published numbers for an upcoming match are the model after
-- the missing players have been folded in, not the model next to a
-- disclaimer. This table is the audit of that step: which side was
-- weakened, by how much, and what the 1X2 was before the adjustment,
-- so the page can say the numbers moved and by how much.
--
-- Kept in ml because the factors are a serving-time prior, not a
-- fitted coefficient, and so they must not leak through a view that
-- a reader could mistake for a measured team strength. The public
-- view exposes only what the sentence on the page needs.
-- ============================================================

create table ml.absence_effect (
  match_id         bigint  not null references core.match(match_id) on delete cascade,
  team_id          integer not null references core.team(team_id),
  attack_factor    numeric not null check (attack_factor > 0 and attack_factor <= 1),
  defence_factor   numeric not null check (defence_factor >= 1),
  missing_key      smallint not null check (missing_key >= 0),
  detail           jsonb   not null default '[]'::jsonb,
  p_home_base      numeric,
  p_draw_base      numeric,
  p_away_base      numeric,
  applied_at       timestamptz not null default now(),
  primary key (match_id, team_id)
);

comment on table ml.absence_effect is 'Serving-time adjustment applied to a fixture because named players are out. attack_factor multiplies that side''s scoring rate; defence_factor multiplies the rate it concedes. The base 1X2 is the unadjusted Dixon-Coles price, stored so the page can show the move.';
comment on column ml.absence_effect.detail is 'Array of {player_id, player_name, status, position, goal_share, minute_share, attack_hit, defence_hit}. One object per absence that contributed, so a reader can see who moved the number.';

create or replace view public.match_effect as
select e.match_id,
       e.team_id,
       t.canonical_name as team,
       e.team_id = m.home_team_id as is_home,
       e.attack_factor,
       e.defence_factor,
       e.missing_key,
       e.detail,
       e.p_home_base,
       e.p_draw_base,
       e.p_away_base
  from ml.absence_effect e
  join core.match m using (match_id)
  join core.team t on t.team_id = e.team_id
 where e.missing_key > 0
    or e.attack_factor < 0.999
    or e.defence_factor > 1.001;

comment on view public.match_effect is 'How reported absences changed this fixture''s probabilities. The numbers on public.prediction already include the adjustment; the base 1X2 here is what the model said before it.';

grant select on public.match_effect to anon, authenticated;
