-- ============================================================
-- Make the expected eleven contain eleven players.
--
-- 0054 partitioned the ranking by `position = 'G'` to keep exactly one
-- goalkeeper. In SQL that expression is null when the position is null,
-- and null is neither true nor false, so players whose position the
-- team sheet never recorded formed a third partition of their own —
-- with their own ranks 1 to 10, all of them marked as starting. CSKA
-- 1948 against Lokomotiv Plovdiv fielded 37.
--
-- coalesce to false: a player with no recorded position is an
-- outfielder for ranking purposes, which is right nine times in ten and
-- is in any case the only useful assumption available.
--
-- Worth stating as a rule rather than a fix. Any three-valued
-- expression used to partition or group silently invents a bucket, and
-- the bucket looks exactly like the others until something counts it.
-- ============================================================

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
                            coalesce(s.position = 'G', false)
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
         when coalesce(position = 'G', false) then rank_in_group = 1
         else rank_in_group <= 10
       end as expected_to_start
  from candidate
 where (coalesce(position = 'G', false) and rank_in_group <= 2)
    or (not coalesce(position = 'G', false) and rank_in_group <= 18);

comment on view public.expected_xi is 'Who is likeliest to start, from the last ten team sheets minus anyone reported out. A guess, useful only until the confirmed sheet appears about an hour before kickoff. expected_to_start marks the eleven; the rest are the likeliest bench.';

grant select on public.expected_xi to anon, authenticated;
