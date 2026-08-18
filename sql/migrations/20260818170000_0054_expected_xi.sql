-- ============================================================
-- A predicted eleven, for the hours before a confirmed one exists.
--
-- The provider publishes the real team sheet about an hour before
-- kickoff. Every hour before that, the honest best guess is who has
-- been starting lately, minus whoever is unavailable.
--
-- Two objects. team_recent_starts counts starts in a club's last ten
-- team sheets and is materialised, because it aggregates every sheet
-- ever loaded and would otherwise be recomputed on every page view —
-- the mistake that made match pages time out in 0049 and 0050.
--
-- expected_xi then picks the goalkeeper with the most starts and the
-- ten outfielders with the most, dropping anyone reported out for that
-- specific fixture. Not by formation: the shape is shown, not solved
-- for. Choosing four defenders because the modal formation says four
-- would produce a tidier answer with no more truth in it, since the
-- ranking cannot tell a full-back from a centre-half anyway.
--
-- Doubtful players stay in. They are more likely to start than the
-- twelfth-choice alternative, and the page marks them.
--
-- The ten-match window is a guess, and a defensible one: shorter and a
-- rotated cup side distorts it, longer and it argues for players who
-- lost their place in September.
-- ============================================================

create materialized view public.team_recent_starts as
with sheets as (
    select l.team_id,
           l.match_id,
           m.kickoff_date,
           row_number() over (
               partition by l.team_id order by m.kickoff_date desc
           ) as recency
      from core.match_lineup l
      join core.match m on m.match_id = l.match_id
     where m.home_goals_ft is not null
),
window_ as (
    select * from sheets where recency <= 10
)
select w.team_id,
       -- Grouped by name, not player_id. core.match_lineup_player is keyed by
       -- (match, team, name) and its player_id is null whenever the provider id
       -- was not resolvable, so grouping on the id splits one footballer into a
       -- resolved row and an unresolved one — which duplicated S. Verdi at
       -- Nijmegen and broke the unique index on the first attempt.
       max(p.player_id) as player_id,
       p.player_name,
       -- The position the player was named in, most recently. The squad list has
       -- one too, and they disagree often enough that the team sheet wins: it is
       -- where he actually played rather than how he is registered.
       (array_agg(p.position order by w.kickoff_date desc)
          filter (where p.position is not null))[1] as position,
       (array_agg(p.shirt_number order by w.kickoff_date desc)
          filter (where p.shirt_number is not null))[1] as shirt_number,
       count(*) filter (where p.is_starter) as starts,
       count(*)                             as named,
       max(w.kickoff_date)                  as last_named
  from window_ w
  join core.match_lineup_player p on p.match_id = w.match_id
                                 and p.team_id = w.team_id
 group by w.team_id, p.player_name;

create unique index team_recent_starts_key
  on public.team_recent_starts (team_id, player_name);
create index team_recent_starts_team_idx
  on public.team_recent_starts (team_id, starts desc);

comment on materialized view public.team_recent_starts is 'Starts in each club''s last ten team sheets. Materialised because it aggregates every sheet loaded and is read once per upcoming fixture. Refreshed by footy build-features.';

create or replace view public.expected_xi as
with candidate as (
    select m.match_id,
           s.team_id,
           s.team_id = m.home_team_id as is_home,
           s.player_name,
           s.position,
           s.shirt_number,
           s.starts,
           s.named,
           ab.status as absence_status,
           ab.reason as absence_reason,
           row_number() over (
               partition by m.match_id, s.team_id,
                            -- Goalkeepers ranked separately, because the eleven
                            -- needs exactly one and the outfield ranking would
                            -- otherwise leave a team with none or two.
                            (s.position = 'G')
               order by s.starts desc, s.named desc, s.player_name
           ) as rank_in_group
      from core.match m
      join public.team_recent_starts s
        on s.team_id in (m.home_team_id, m.away_team_id)
      left join core.match_absence ab
             on ab.match_id = m.match_id
            and ab.team_id = s.team_id
            and core.norm_name(ab.player_name) = core.norm_name(s.player_name)
     where m.home_goals_ft is null
       and m.status = 'scheduled'
       and m.kickoff_date between current_date - 1 and current_date + 14
       -- Reported out means out. Doubtful players stay: they are likelier to
       -- start than whoever is next in the ranking, and the page says so.
       and (ab.status is null or ab.status <> 'out')
)
select match_id,
       team_id,
       is_home,
       player_name,
       position,
       shirt_number,
       starts,
       named,
       absence_status,
       absence_reason,
       case
         when position = 'G' then rank_in_group = 1
         else rank_in_group <= 10
       end as expected_to_start
  from candidate
 where (position = 'G' and rank_in_group <= 2)
    or (position is distinct from 'G' and rank_in_group <= 18);

comment on view public.expected_xi is 'Who is likeliest to start, from the last ten team sheets minus anyone reported out. A guess, and only useful until the confirmed sheet appears about an hour before kickoff. expected_to_start marks the eleven; the rest are the likeliest bench.';

grant select on public.team_recent_starts, public.expected_xi to anon, authenticated;
