import Link from "next/link";
import { notFound } from "next/navigation";
import { MarketCard } from "@/components/MarketCard";
import { formatDateLong } from "@/lib/format";
import { supabase } from "@/lib/supabase";
import {
  COMPETITIONS,
  type Fixture,
  type HeadToHead,
  type Market,
  type MarketPrice,
  type Prediction,
  type TeamForm,
} from "@/lib/types";

export const revalidate = 300;

// Preferred order: result first, then the goals family, then the count markets,
// which is roughly the order of how much a reader cares and puts the markets
// with a price to compare against near the top.
//
// This ranks markets, it does not choose them. Whether a market may be published
// is decided in ml.market.status and enforced by the view, so filtering on a list
// here would mean a market earning publication and silently not appearing.
// Anything unranked sorts to the end rather than vanishing.
const ORDER = [
  "goals_1x2",
  "goals_total",
  "goals_btts",
  "goals_home",
  "goals_away",
  "corners_home",
  "corners_away",
  "shots_total",
  "shots_home",
  "shots_away",
  "fouls_total",
];

function rank(code: string) {
  const i = ORDER.indexOf(code);
  return i === -1 ? ORDER.length : i;
}

const NO_PRICE = "No bookmaker in this dataset prices this market.";

function sortRows(a: Prediction, b: Prediction) {
  const order = ["home", "draw", "away", "over", "under", "yes", "no"];
  const lineA = a.line === null ? -1 : Number(a.line);
  const lineB = b.line === null ? -1 : Number(b.line);
  if (lineA !== lineB) return lineA - lineB;
  return order.indexOf(a.selection) - order.indexOf(b.selection);
}

export default async function MatchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const matchId = Number(id);
  if (!Number.isFinite(matchId)) notFound();

  const [fixtureRes, predictionRes, priceRes, formRes, h2hRes, marketRes] =
    await Promise.all([
      supabase.from("fixture").select("*").eq("match_id", matchId).maybeSingle(),
      supabase.from("prediction").select("*").eq("match_id", matchId),
      supabase.from("market_price").select("*").eq("match_id", matchId),
      supabase.from("team_form").select("*").eq("match_id", matchId),
      supabase.from("head_to_head").select("*").eq("match_id", matchId).maybeSingle(),
      supabase.from("market").select("market_code,label"),
    ]);

  const fixture = fixtureRes.data as Fixture | null;
  if (!fixture) notFound();

  const predictions = (predictionRes.data ?? []) as Prediction[];
  const prices = (priceRes.data ?? []) as MarketPrice[];
  const forms = (formRes.data ?? []) as TeamForm[];
  const h2h = h2hRes.data as HeadToHead | null;

  const home = forms.find((f) => f.is_home);
  const away = forms.find((f) => !f.is_home);
  const played =
    fixture.home_goals_ft !== null && fixture.away_goals_ft !== null;

  const labels = new Map<string, string>(
    ((marketRes.data ?? []) as Array<Pick<Market, "market_code" | "label">>).map(
      (m) => [m.market_code, m.label]
    )
  );

  const byMarket = new Map<string, Prediction[]>();
  for (const p of predictions) {
    const list = byMarket.get(p.market_code) ?? [];
    list.push(p);
    byMarket.set(p.market_code, list);
  }

  return (
    <div className="space-y-8">
      <Link href="/" className="text-sm text-muted transition hover:text-foreground">
        ← All fixtures
      </Link>

      <header className="rounded-lg border border-border bg-surface p-6">
        <p className="text-xs uppercase tracking-widest text-muted">
          {COMPETITIONS[fixture.competition_code] ?? fixture.competition_code} ·{" "}
          {fixture.season}
          {fixture.matchday ? ` · matchday ${fixture.matchday}` : ""}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {fixture.home_team}
            <span className="mx-3 text-muted">v</span>
            {fixture.away_team}
          </h1>
          {played && (
            <span className="tnum rounded bg-surface-raised px-2.5 py-1 text-lg font-semibold">
              {fixture.home_goals_ft}–{fixture.away_goals_ft}
            </span>
          )}
        </div>
        <p className="mt-2 text-sm text-muted">
          {formatDateLong(fixture.kickoff_date)}
          {fixture.venue_name ? ` · ${fixture.venue_name}` : ""}
        </p>
        <p className="mt-3 text-sm">
          <span className="text-muted">Season history: </span>
          <Link
            href={`/team/${fixture.home_team_id}?competition=${encodeURIComponent(
              fixture.competition_code
            )}&season=${encodeURIComponent(fixture.season)}`}
            className="text-accent transition hover:underline"
          >
            {fixture.home_team}
          </Link>
          <span className="mx-2 text-muted">·</span>
          <Link
            href={`/team/${fixture.away_team_id}?competition=${encodeURIComponent(
              fixture.competition_code
            )}&season=${encodeURIComponent(fixture.season)}`}
            className="text-accent transition hover:underline"
          >
            {fixture.away_team}
          </Link>
        </p>
      </header>

      {predictions.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-6 text-sm text-muted">
          No published markets for this fixture.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {[...byMarket.keys()]
            .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
            .map((code) => {
            const rows = [...(byMarket.get(code) ?? [])].sort(sortRows);
            const marketPrices = prices.filter((p) => p.market_code === code);
            return (
              <MarketCard
                key={code}
                title={labels.get(code) ?? code}
                subtitle={marketPrices.length === 0 ? NO_PRICE : undefined}
                rows={rows}
                prices={marketPrices}
                teamNames={
                  code === "goals_1x2"
                    ? { home: fixture.home_team, away: fixture.away_team }
                    : undefined
                }
              />
            );
          })}
        </div>
      )}

      {home && away && (
        <section className="overflow-hidden rounded-lg border border-border bg-surface">
          <header className="border-b border-border px-4 py-3">
            <h3 className="text-sm font-medium">Form before kickoff</h3>
            <p className="mt-0.5 text-xs text-muted">
              Averages over the previous ten matches. Every value was knowable
              before this match was played.
            </p>
          </header>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wider text-muted">
                <th className="px-4 py-2 text-left font-medium">Metric</th>
                <th className="px-3 py-2 text-right font-medium">
                  {fixture.home_team_short}
                </th>
                <th className="px-4 py-2 text-right font-medium">
                  {fixture.away_team_short}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              <FormRow label="Points per game" a={home.ppg_10} b={away.ppg_10} />
              <FormRow label="Goals for" a={home.gf_10} b={away.gf_10} />
              <FormRow label="Goals against" a={home.ga_10} b={away.ga_10} />
              <FormRow label="Expected goals for" a={home.xgf_10} b={away.xgf_10} />
              <FormRow
                label="Expected goals against"
                a={home.xga_10}
                b={away.xga_10}
              />
              <FormRow label="Corners won" a={home.corners_f_10} b={away.corners_f_10} />
              <FormRow label="Shots" a={home.shots_f_10} b={away.shots_f_10} />
              <FormRow label="Fouls" a={home.fouls_10} b={away.fouls_10} />
              <FormRow
                label="Days since last match"
                a={home.rest_days}
                b={away.rest_days}
                digits={0}
              />
            </tbody>
          </table>
        </section>
      )}

      {h2h && (h2h.h2h_matches ?? 0) > 0 && (
        <section className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-medium">Head to head</h3>
          <p className="mt-2 text-sm text-muted">
            {h2h.h2h_matches} previous meetings in this competition:{" "}
            <span className="text-foreground">{h2h.h2h_home_wins}</span> home wins,{" "}
            <span className="text-foreground">{h2h.h2h_draws}</span> draws,{" "}
            <span className="text-foreground">{h2h.h2h_away_wins}</span> away wins,
            averaging{" "}
            <span className="text-foreground">
              {Number(h2h.h2h_avg_goals ?? 0).toFixed(2)}
            </span>{" "}
            goals and{" "}
            <span className="text-foreground">
              {Number(h2h.h2h_avg_corners ?? 0).toFixed(1)}
            </span>{" "}
            corners.
          </p>
        </section>
      )}
    </div>
  );
}

function FormRow({
  label,
  a,
  b,
  digits = 2,
}: {
  label: string;
  a: number | null;
  b: number | null;
  digits?: number;
}) {
  const format = (v: number | null) =>
    v === null ? "—" : Number(v).toFixed(digits);
  const better = a !== null && b !== null && Number(a) !== Number(b);
  return (
    <tr>
      <td className="px-4 py-2 text-muted">{label}</td>
      <td
        className={`tnum px-3 py-2 text-right ${
          better && Number(a) > Number(b) ? "font-medium" : ""
        }`}
      >
        {format(a)}
      </td>
      <td
        className={`tnum px-4 py-2 text-right ${
          better && Number(b) > Number(a) ? "font-medium" : ""
        }`}
      >
        {format(b)}
      </td>
    </tr>
  );
}
