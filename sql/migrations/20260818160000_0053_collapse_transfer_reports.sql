-- ============================================================
-- Collapse the republished transfers the last attempt missed.
--
-- 0052 bucketed dates into fortnights and kept one row per bucket.
-- Cheaper than comparing pairs and wrong for the same reason any
-- fixed grid is: two reports a day apart land in different buckets
-- whenever they straddle a boundary. Trossard to Beşiktaş survived
-- twice, on 12 and 13 July, and Kiwior to Porto on 29 and 30 June.
--
-- The rule here has no boundaries to straddle: delete a row when a
-- later row describes the same player moving between the same two
-- clubs within a fortnight. Chains collapse to their latest link,
-- which is the confirmed report.
--
-- Direction is part of the key, so Kiwior returning from a loan at
-- Porto on 29 June and being sold to Porto on 30 June remain two
-- events, which they are.
-- ============================================================

delete from core.transfer t
 where exists (
        select 1 from core.transfer later
         where later.player_id = t.player_id
           and later.from_name is not distinct from t.from_name
           and later.to_name is not distinct from t.to_name
           and later.moved_on > t.moved_on
           and later.moved_on - t.moved_on <= 14);
