-- ============================================================
-- Allow an event before kickoff.
--
-- The minute was constrained to 0-130 on the assumption that a match
-- starts at zero. The feed reports negative minutes: a yellow card at
-- minute -5, which is a booking in the tunnel or the warm-up. Rare,
-- and real.
--
-- Clamping it to zero was the alternative and is worse — it would put
-- a pre-match booking in the first fifteen minutes of play, which is
-- exactly the kind of quiet distortion that makes a timing chart
-- untrustworthy. The band calculation already folds anything below
-- minute one into the first band, so a negative minute displays
-- sensibly without pretending it happened after the whistle.
--
-- The floor is -30 rather than unbounded, because a minute of -400 is
-- a parsing error rather than an early booking and should still be
-- rejected.
-- ============================================================

alter table core.match_event drop constraint match_event_minute_check;

alter table core.match_event add constraint match_event_minute_check
  check (minute between -30 and 130);

comment on column core.match_event.minute is 'Minute of play. Negative for events before kickoff, which the feed reports for bookings in the tunnel; timing charts fold anything below minute one into the first band rather than treating it as first-half play.';
