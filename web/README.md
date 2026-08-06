# Footy Analytics — web

The reading end of the pipeline. Next.js App Router, server components, talking
to Supabase through the publishable key.

```bash
cp .env.example .env.local     # fill in the project URL and publishable key
npm install
npm run dev                    # http://localhost:3000
```

Node 24 is what this was built and tested against.

## Pages

| Route | Shows |
|---|---|
| `/` | Fixtures with stored probabilities, filterable by league |
| `/match/[id]` | Every published market for one fixture, the closing price beside it, pre-match form, head to head |
| `/accuracy` | Predicted against realised frequency for every shipping market |

## What it can and cannot read

Every query goes through the nine views in `public`. The `anon` role has no
access to `core`, `ml`, `features` or `raw` — not restricted access, none — so
the app physically cannot show a held market, an uncalibrated probability, or a
model coefficient. That is asserted in `tests/test_public_surface.py` rather
than left to convention.

The practical consequence when working here: if a number is not on the screen,
check whether the view exposes it before reaching for the client. Adding a
column to a view publishes it to the world.

## The one thing worth understanding

`public.prediction` returns rows the database never stored. Over/under and
both-teams-to-score are held only as the positive side, and the complement is
generated in SQL. That is deliberate — `under = 1 - over` is arithmetic a client
should never be trusted with, because a rounding or filtering slip there ships a
wrong price with no error anywhere. Rows carry `is_stored` so the distinction is
visible, and `hit` is inverted on the generated side.

## Where the market column comes from

Only 1X2 and total goals have bookmaker prices in this database, de-vigged and
taken at the close. Corners, fouls and shots have none, and those cards say so
in words rather than showing an empty column. That absence is not a gap to fill
later — it is most of the reason those markets are worth modelling.

## Deploying

Vercel, with the two environment variables set. Pages revalidate every five
minutes; predictions change only when `footy predict` runs, so there is nothing
to gain from anything tighter.
