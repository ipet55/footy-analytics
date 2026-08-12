-- ============================================================
-- Derive market labels from stat and scope instead of listing them.
--
-- The label was a CASE over nine known market codes with an
-- initcap fallback, which was fine while those nine were the only
-- ones published. Promoting per-team shots exposed the fallback:
-- it renders 'Shots Home' beside 'Home corners' and 'Home goals'.
--
-- Every market is already described by its own columns, so the
-- label can be composed from them and the next market promoted
-- gets a correct name without anybody remembering to add it here.
-- The nine existing labels are unchanged by the new rule, which is
-- what makes this safe to apply to a live view.
--
-- create or replace preserves the grants to anon and authenticated;
-- the column list and order are identical for the same reason.
-- ============================================================

create or replace view public.market as
select market_code,
       stat,
       scope,
       kind,
       case
         when kind = 'outcome' then 'Match result'
         when kind = 'btts'    then 'Both teams to score'
         when scope = 'match'  then 'Total ' || stat
         when scope = 'home'   then 'Home ' || stat
         when scope = 'away'   then 'Away ' || stat
         else initcap(replace(market_code, '_', ' '))
       end as label,
       notes
  from ml.market m
 where status = 'shipping';

comment on view public.market is 'Markets the database permits publishing, with a display label composed from stat and scope so a newly promoted market is named correctly without a code change.';
