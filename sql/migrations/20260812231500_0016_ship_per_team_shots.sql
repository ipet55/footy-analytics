-- ============================================================
-- Promote per-team shots to shipping.
--
-- It was held on calibration, with worst reliability buckets of
-- 14.8% in France and 13.3% in Italy against a standard of about
-- 8%. Both numbers turn out to have been an artifact rather than a
-- property of the market.
--
-- Teams absent from a fit defaulted to a parameter of zero. For
-- `concede`, which carries the whole level of the count, zero means
-- about one shot a match instead of twelve. In a walk-forward
-- backtest that fires three times a league every season, on the
-- clubs promoted into it, and the resulting handful of absurd
-- probabilities is what the worst-bucket statistic reports. Fixing
-- the default to the league average was done to stop a crash on the
-- 2026-27 promoted clubs; re-measuring afterwards shows it also
-- removed the only thing keeping this market back.
--
-- Verified by restoring the old defaults, which reproduces the
-- documented figures exactly (France 14.8%, Italy 13.3%, England
-- 9.7%) and confirms the causal link rather than assuming it.
--
-- The market now passes both criteria in all thirty combinations of
-- five leagues, three lines and two sides: ranking gains of 5.2% to
-- 13.7% and worst buckets of 1.1% to 7.0%. Every line inside the
-- market qualifies, which matters because status is per market and
-- shipping one would otherwise publish its bad lines too. That is
-- exactly why per-team fouls stays held: its signal is now positive
-- everywhere, but the 12.5 line still miscalibrates in three leagues.
-- ============================================================

update ml.market
   set status = 'shipping',
       notes  = 'Strongest market in the project: 8.5-13.7% over the rolling benchmark, positive in all five leagues at all three lines, worst reliability bucket 1.1-7.0%. Held until 2026-08-12 on a miscalibration that was an artifact of unknown teams defaulting to a concede of zero, priced at one shot a match instead of twelve.'
 where market_code = 'shots_home';

update ml.market
   set status = 'shipping',
       notes  = 'Ships on the same evidence as shots_home: 5.2-12.7% over the benchmark across five leagues and three lines, worst reliability bucket 2.4-7.0%.'
 where market_code = 'shots_away';

update ml.market
   set notes = 'Signal is now positive in all five leagues at every line, 2.6-9.1%, after the unknown-team default was fixed — the Germany negative recorded earlier has gone. Still held on calibration, and specifically on the 12.5 line, which misses the standard in Germany, Spain and Italy. The 8.5 line would qualify on its own; status is per market rather than per line, so shipping it would publish 12.5 as well.'
 where market_code in ('fouls_home', 'fouls_away');
