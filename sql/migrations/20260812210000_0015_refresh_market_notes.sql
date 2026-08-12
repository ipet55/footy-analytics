-- ============================================================
-- Bring ml.market.notes back in line with what has been measured.
--
-- The registry is the source of truth for whether a market may be
-- published, so a stale note there is worse than a stale note in a
-- document: it is the thing somebody reads before deciding whether
-- to trust a number. Two had gone out of date.
--
-- cards_total blamed its calibration on referees being recorded for
-- the Premier League only. That was true when it was written and is
-- no longer: referees are now backfilled from the FBref schedule at
-- 100% coverage in all five leagues, and cards still do not ship.
-- The reason is narrower than the note claimed — the referee term
-- helps only where referees actually vary.
--
-- shots_home quoted 4.4-7.6%, which was measured through the count
-- fit bug that had per-team models diverging. Post-fix the market is
-- much stronger and still held, on calibration rather than signal.
--
-- Statuses are deliberately unchanged. Nothing here has earned
-- publication; only the explanations were wrong.
-- ============================================================

update ml.market
   set notes = 'Real but small, and it is the referee term that carries it: Spain gains 0.0077 and Italy 0.0118, the three leagues where officials vary less gain nothing. Referees are now 100% covered in all five leagues, so the earlier explanation — that only the Premier League recorded them — no longer applies. Italy alone would qualify; Germany and France are nowhere near.'
 where market_code = 'cards_total';

update ml.market
   set notes = 'Strongest signal in the project outside fouls totals: 1.4-11.7% gain, positive in all five leagues at every line, after the count-fit divergence was fixed. The earlier 4.4-7.6% was measured through that bug. Held on calibration, not signal — worst reliability buckets of 14.8% in France and 13.3% in Italy against a standard of about 8%.'
 where market_code = 'shots_home';

update ml.market
   set notes = 'Same signal and the same calibration problem as the home side; see shots_home.'
 where market_code = 'shots_away';

update ml.market
   set notes = 'Held on signal as well as calibration, which is what separates it from per-team shots: Germany is still negative at the 8.5 line and worst reliability buckets reach 19.5%.'
 where market_code = 'fouls_home';
