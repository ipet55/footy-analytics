-- ============================================================
-- Judge every count market in the four newly published leagues.
--
-- They showed six to eight markets against England's eleven, and the
-- reason was not that the rest had been rejected: only four count
-- markets per league had ever been measured, at one line each.
-- Corners away, shots per team and per-team fouls were absent rather
-- than judged.
--
-- This records the full walk-forward — every scope, every line — and
-- lets the thresholds be applied here rather than by hand, so the
-- evidence and the verdict cannot drift apart. Both conditions must
-- hold at *every* line, because status has no line dimension and a
-- market is published whole or not at all.
--
-- The gain floor is new and deserves stating. Positive-at-every-line
-- turns out to admit markets gaining 0.2%, which passes the letter of
-- the standard and means nothing: corner totals clear it in three of
-- these leagues while the original five found no signal there at all,
-- and the mechanism behind that finding — dominance moves corners
-- between the sides rather than creating them — does not stop being
-- true in the Eredivisie. A floor of 1% is set by precedent rather
-- than taste: shots totals ship globally on a minimum of 0.8%, so
-- anything below about a point is inside the range the project has
-- already treated as noise.
--
-- Three earlier calls are corrected. Eredivisie fouls totals and home
-- corners, and Süper Lig fouls totals, were shipped on a single line's
-- evidence and fail once every line is checked — 8.7% and 8.1%
-- calibration, and a negative gain respectively. Publishing them was
-- the predictable cost of measuring one line and generalising.
-- ============================================================

create temporary table _evidence (
    market text, league text, gain_min numeric, gain_max numeric, worst numeric
) on commit drop;

insert into _evidence values
  ('corners_total','NED-ED', 0.2, 0.9, 7.8), ('corners_home','NED-ED', 6.1, 7.6, 8.1),
  ('corners_away','NED-ED', 6.9, 8.3, 9.2), ('shots_total','NED-ED', 1.9, 3.1, 4.0),
  ('shots_home','NED-ED',14.2,17.6, 4.6),    ('shots_away','NED-ED',17.5,18.8, 8.5),
  ('fouls_total','NED-ED', 4.0, 4.7, 8.7),   ('fouls_home','NED-ED', 3.0, 4.3, 7.8),
  ('fouls_away','NED-ED', 4.3, 4.8, 9.8),    ('cards_total','NED-ED',-0.1, 0.1,10.0),
  ('cards_home','NED-ED', 0.4, 1.0, 6.5),    ('cards_away','NED-ED',-0.0, 0.5, 8.2),

  ('corners_total','POR-PL', 0.8, 2.7, 8.0), ('corners_home','POR-PL',10.3,11.8, 9.7),
  ('corners_away','POR-PL', 6.0, 8.3, 5.1),  ('shots_total','POR-PL', 3.1, 3.8, 5.6),
  ('shots_home','POR-PL',16.2,18.4, 9.3),    ('shots_away','POR-PL',13.3,16.8, 5.5),
  ('fouls_total','POR-PL', 5.0, 9.1, 4.8),   ('fouls_home','POR-PL', 5.5, 7.1, 9.0),
  ('fouls_away','POR-PL', 4.9, 7.1, 6.2),    ('cards_total','POR-PL', 0.2, 0.9, 9.4),
  ('cards_home','POR-PL', 1.6, 3.1, 6.0),    ('cards_away','POR-PL',-0.8, 0.3,13.4),

  ('corners_total','TUR-SL', 0.4, 1.2, 3.2), ('corners_home','TUR-SL', 1.6, 5.5, 5.8),
  ('corners_away','TUR-SL', 3.3, 4.2, 7.9),  ('shots_total','TUR-SL', 3.1, 4.4, 7.7),
  ('shots_home','TUR-SL', 5.8,10.6, 8.2),    ('shots_away','TUR-SL', 7.6,11.1, 7.0),
  ('fouls_total','TUR-SL',-0.1, 1.9, 9.4),   ('fouls_home','TUR-SL', 3.9, 5.6, 4.1),
  ('fouls_away','TUR-SL', 2.8, 3.4, 4.6),    ('cards_total','TUR-SL', 0.2, 0.5, 8.6),
  ('cards_home','TUR-SL', 0.5, 2.8, 8.1),    ('cards_away','TUR-SL',-0.4, 0.7, 4.2),

  ('corners_total','BEL-PL', 0.3, 0.7, 6.4), ('corners_home','BEL-PL', 0.4, 3.6, 7.4),
  ('corners_away','BEL-PL', 0.9, 3.5,10.2),  ('shots_total','BEL-PL', 1.9, 2.2, 7.5),
  ('shots_home','BEL-PL',10.6,13.6, 5.7),    ('shots_away','BEL-PL', 6.9, 7.2, 7.0),
  ('fouls_total','BEL-PL', 3.1, 4.6, 9.2),   ('fouls_home','BEL-PL', 1.7, 2.9, 5.1),
  ('fouls_away','BEL-PL', 2.9, 4.3,10.2),    ('cards_total','BEL-PL', 0.9, 2.5, 6.3),
  ('cards_home','BEL-PL', 0.8, 2.5, 6.1),    ('cards_away','BEL-PL', 1.6, 3.3, 4.3);

-- Replace every count verdict for these four leagues. Goals markets are left
-- alone: they come from a different model and were validated against odds.
delete from ml.market_competition mc
 using ml.market m, core.competition c
 where m.market_code = mc.market_code
   and c.competition_id = mc.competition_id
   and m.stat <> 'goals'
   and c.code in ('NED-ED', 'POR-PL', 'TUR-SL', 'BEL-PL');

insert into ml.market_competition (market_code, competition_id, status, notes)
select e.market, c.competition_id,
       case when e.gain_min >= 1.0 and e.worst <= 8.0 then 'shipping' else 'held' end,
       format(
         'Walk-forward from 2022/23, every line: gain %s to %s%%, worst reliability '
         || 'bucket %s%%. %s',
         e.gain_min, e.gain_max, e.worst,
         case
           when e.gain_min >= 1.0 and e.worst <= 8.0 then 'Both criteria met at every line.'
           when e.gain_min <= 0 then 'Negative at one or more lines.'
           when e.gain_min < 1.0 then 'Gain inside the range the project treats as noise.'
           else 'Calibration outside the 8% standard.'
         end
       )
  from _evidence e
  join core.competition c on c.code = e.league
  join ml.market m on m.market_code = e.market;
