import Link from "next/link";
import { notFound } from "next/navigation";
import { formatDateShort } from "@/lib/format";
import { supabase } from "@/lib/supabase";
import {
  COMPETITIONS,
  type Fixture,
  type TeamSeasonSummary,
  type TeamSeasonVenue,
} from "@/lib/types";

export const revalidate = 300;

// The order measures read in, most asked-about first. Anything not listed still
// renders, after these — the view decides what exists, not this list.
const MEASURE_ORDER = [
  "goals scored",
  "goals conceded",
  "goals total",
  "corners for",
  "corners against",
  "corners total",
  "shots",
  "fouls",
  "cards",
];

function rank(measure: string) {
  const i = MEASURE_ORDER.indexOf(measure);
  return i === -1 ? MEASURE_ORDER.length : i;
}

function pct(value: number) {
  return `${(Number(value) * 100).toFixed(0)}%`;
}

/** Postgres numerics arrive as strings often enough that trusting the declared
 *  type produces a column reading "16.053" beside one reading "13". */
function num(value: number, places = 2) {
  return Number(value).toFixed(places);
}

export default async function TeamPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ season?: string; competition?: string }>;
}) {
  const { id } = await params;
  const teamId = Number(id);
  if (!Number.isFinite(teamId)) notFound();
  const { season: wantSeason, competition: wantCompetition } = await searchParams;

  const [summaryRes, venueRes] = await Promise.all([
    supabase
      .from("team_season_summary")
      .select("*")
      .eq("team_id", teamId)
      .order("start_year", { ascending: false }),
    supabase.from("team_season_venue").select("*").eq("team_id", teamId),
  ]);

  const allRows = (summaryRes.data ?? []) as TeamSeasonSummary[];
  if (allRows.length === 0) notFound();

  const teamName = allRows[0].team;

  // Seasons a team appeared in, newest first, each tied to its competition —
  // a club can be in two at once, so the pair is the unit, not the season.
  const periods = [
    ...new Map(
      allRows.map((r) => [
        `${r.competition_code}|${r.season}`,
        { competition: r.competition_code, season: r.season, year: r.start_year },
      ])
    ).values(),
  ].sort((a, b) => b.year - a.year || a.competition.localeCompare(b.competition));

  const selected =
    periods.find(
      (p) =>
        (!wantSeason || p.season === wantSeason) &&
        (!wantCompetition || p.competition === wantCompetition)
    ) ?? periods[0];

  const rows = allRows.filter(
    (r) => r.season === selected.season && r.competition_code === selected.competition
  );
  const venues = ((venueRes.data ?? []) as TeamSeasonVenue[]).filter(
    (v) => v.season === selected.season && v.competition_code === selected.competition
  );
  const home = venues.find((v) => v.venue === "home");
  const away = venues.find((v) => v.venue === "away");

  const byMeasure = new Map<string, TeamSeasonSummary[]>();
  for (const row of rows) {
    const list = byMeasure.get(row.measure) ?? [];
    list.push(row);
    byMeasure.set(row.measure, list);
  }
  const measures = [...byMeasure.entries()].sort(
    (a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])
  );

  const matches = rows[0]?.matches ?? 0;

  const recentRes = await supabase
    .from("fixture")
    .select("*")
    .or(`home_team_id.eq.${teamId},away_team_id.eq.${teamId}`)
    .eq("competition_code", selected.competition)
    .eq("season", selected.season)
    .not("home_goals_ft", "is", null)
    .order("kickoff_date", { ascending: false })
    .limit(10);
  const recent = (recentRes.data ?? []) as Fixture[];

  return (
    <div className="space-y-8">
      <Link href="/" className="text-sm text-muted transition hover:text-foreground">
        ← All fixtures
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{teamName}</h1>
        <p className="mt-1 text-sm text-muted">
          {COMPETITIONS[selected.competition] ?? selected.competition} ·{" "}
          {selected.season} · {matches} matches played
        </p>
      </header>

      {periods.length > 1 && (
        <nav className="flex flex-wrap gap-2">
          {periods.slice(0, 16).map((p) => {
            const active =
              p.season === selected.season && p.competition === selected.competition;
            return (
              <Link
                key={`${p.competition}|${p.season}`}
                href={`/team/${teamId}?competition=${encodeURIComponent(
                  p.competition
                )}&season=${encodeURIComponent(p.season)}`}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  active
                    ? "border-accent/50 bg-accent/10 text-accent"
                    : "border-border bg-surface text-muted hover:text-foreground"
                }`}
              >
                {p.season}
                <span className="ml-1.5 opacity-60">
                  {COMPETITIONS[p.competition] ?? p.competition}
                </span>
              </Link>
            );
          })}
        </nav>
      )}

      <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
        These are counts of what happened in the matches this team played, not
        forecasts. They take no account of who the opponent was, so a high rate
        here says nothing on its own about the next fixture — the model
        probabilities on a match page do that job.
      </p>

      {home && away && (
        <section>
          <h2 className="mb-3 text-sm font-semibold tracking-tight">
            Home and away
          </h2>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-widest text-muted">
                  <th className="px-4 py-2 text-left font-medium">Split</th>
                  <th className="px-4 py-2 text-right font-medium">Games</th>
                  <th className="px-4 py-2 text-right font-medium">Scored</th>
                  <th className="px-4 py-2 text-right font-medium">Conceded</th>
                  <th className="px-4 py-2 text-right font-medium">Corners</th>
                  <th className="px-4 py-2 text-right font-medium">Shots</th>
                  <th className="px-4 py-2 text-right font-medium">Pts/game</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[home, away].map((v) => (
                  <tr key={v.venue}>
                    <td className="px-4 py-2 capitalize">{v.venue}</td>
                    <td className="tnum px-4 py-2 text-right text-muted">{v.matches}</td>
                    <td className="tnum px-4 py-2 text-right">{num(v.goals_for)}</td>
                    <td className="tnum px-4 py-2 text-right">{num(v.goals_against)}</td>
                    <td className="tnum px-4 py-2 text-right">{num(v.corners_for)}</td>
                    <td className="tnum px-4 py-2 text-right">{num(v.shots_for)}</td>
                    <td className="tnum px-4 py-2 text-right">{num(v.points_per_game)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight">
          How often each line was passed
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {measures.map(([measure, lines]) => (
            <div
              key={measure}
              className="overflow-hidden rounded-lg border border-border bg-surface"
            >
              <header className="border-b border-border px-4 py-3">
                <h3 className="text-sm font-medium capitalize">{measure}</h3>
                <p className="mt-0.5 text-xs text-muted">
                  {num(lines[0].mean_value)} per match across {lines[0].matches} games
                </p>
              </header>
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  {[...lines]
                    .sort((a, b) => a.line - b.line)
                    .map((row) => (
                      <tr key={row.line}>
                        <td className="px-4 py-2">
                          Over <span className="text-muted">{row.line}</span>
                        </td>
                        <td className="tnum px-4 py-2 text-right text-xs text-muted">
                          {row.over_count} of {row.matches}
                        </td>
                        <td className="tnum px-4 py-2 text-right font-medium">
                          {pct(row.over_rate)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </section>

      {recent.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold tracking-tight">Recent results</h2>
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
            {recent.map((m) => (
              <li key={m.match_id}>
                <Link
                  href={`/match/${m.match_id}`}
                  className="grid grid-cols-[auto_1fr_auto] items-center gap-4 px-4 py-3 transition hover:bg-surface-raised"
                >
                  <span className="w-28 shrink-0 text-xs text-muted">
                    {formatDateShort(m.kickoff_date)}
                  </span>
                  <span className="min-w-0 truncate text-sm">
                    <span
                      className={
                        m.home_team_id === teamId ? "font-medium" : "text-muted"
                      }
                    >
                      {m.home_team}
                    </span>
                    <span className="mx-2 text-muted">v</span>
                    <span
                      className={
                        m.away_team_id === teamId ? "font-medium" : "text-muted"
                      }
                    >
                      {m.away_team}
                    </span>
                  </span>
                  <span className="tnum text-sm">
                    {m.home_goals_ft}–{m.away_goals_ft}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
