import Link from "next/link";
import { notFound } from "next/navigation";
import { GoalTiming } from "@/components/GoalTiming";
import { formatDateShort } from "@/lib/format";
import { supabase } from "@/lib/supabase";
import {
  COMPETITIONS,
  type Fixture,
  type TeamSeasonFirst,
  type TeamSeasonLine,
  type TeamSeasonMeasure,
  type TeamSeasonTiming,
  type Venue,
} from "@/lib/types";

export const revalidate = 300;

const VENUES: Venue[] = ["overall", "home", "away"];
const VENUE_LABEL: Record<Venue, string> = {
  overall: "Overall",
  home: "At home",
  away: "At away",
};

// Measures paired so a table reads as one subject: what the team did, then what
// was done to it. The "against" side is the second column group of the same
// card rather than a card of its own, because the comparison is the point.
const GROUPS: Array<{ title: string; forMeasure: string; againstMeasure?: string }> = [
  { title: "Corners", forMeasure: "corners for", againstMeasure: "corners against" },
  { title: "Goals", forMeasure: "goals scored", againstMeasure: "goals conceded" },
  { title: "Corners in the match", forMeasure: "corners total" },
  { title: "Goals in the match", forMeasure: "goals total" },
  { title: "Shots", forMeasure: "shots" },
  { title: "Fouls", forMeasure: "fouls" },
  { title: "Cards", forMeasure: "cards" },
];

function pct(value: number | null) {
  return value === null ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function num(value: number, places = 2) {
  return Number(value).toFixed(places);
}

/** Green through to red, by how often something happened. Mirrors how these
 *  tables are read everywhere else: the colour is the first thing scanned and
 *  the number confirms it. */
function heat(rate: number | null) {
  if (rate === null) return "text-muted";
  const r = Number(rate);
  if (r >= 0.8) return "text-edge-positive";
  if (r >= 0.6) return "text-foreground";
  if (r >= 0.4) return "text-muted";
  return "text-edge-negative";
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

  // Two round trips rather than one, because the second has to be filtered to a
  // single season. A club with a long European record has thousands of line
  // rows, and an unfiltered fetch silently stops at the API's default page size
  // — leaving the tables empty while every other part of the page renders, which
  // looks like a layout bug rather than a truncated read.
  const measureRes = await supabase
    .from("team_season_measure")
    .select("*")
    .eq("team_id", teamId)
    .order("start_year", { ascending: false })
    .limit(4000);

  const allMeasures = (measureRes.data ?? []) as TeamSeasonMeasure[];
  if (allMeasures.length === 0) notFound();

  const teamName = allMeasures[0].team;

  // A club can be in two competitions at once, so the unit is the pair.
  const periods = [
    ...new Map(
      allMeasures.map((r) => [
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

  const measures = allMeasures.filter(
    (r) => r.season === selected.season && r.competition_code === selected.competition
  );

  const [lineRes, timingRes, firstRes] = await Promise.all([
    supabase
      .from("team_season_line")
      .select("*")
      .eq("team_id", teamId)
      .eq("competition_code", selected.competition)
      .eq("season", selected.season)
      .limit(2000),
    supabase
      .from("team_season_timing")
      .select("*")
      .eq("team_id", teamId)
      .eq("competition_code", selected.competition)
      .eq("season", selected.season)
      .eq("venue", "overall"),
    supabase
      .from("team_season_first")
      .select("*")
      .eq("team_id", teamId)
      .eq("competition_code", selected.competition)
      .eq("season", selected.season)
      .eq("venue", "overall")
      .maybeSingle(),
  ]);
  const lines = (lineRes.data ?? []) as TeamSeasonLine[];
  const timing = (timingRes.data ?? []) as TeamSeasonTiming[];
  const first = firstRes.data as TeamSeasonFirst | null;

  const measureAt = (measure: string, venue: Venue) =>
    measures.find((m) => m.measure === measure && m.venue === venue);
  const linesFor = (measure: string) => {
    const values = [
      ...new Set(lines.filter((l) => l.measure === measure).map((l) => Number(l.line))),
    ].sort((a, b) => a - b);
    return values.map((line) => ({
      line,
      byVenue: Object.fromEntries(
        VENUES.map((v) => [
          v,
          lines.find(
            (l) => l.measure === measure && l.venue === v && Number(l.line) === line
          ) ?? null,
        ])
      ) as Record<Venue, TeamSeasonLine | null>,
    }));
  };

  const overall = measureAt("goals scored", "overall");

  const recentRes = await supabase
    .from("fixture")
    .select("*")
    .or(`home_team_id.eq.${teamId},away_team_id.eq.${teamId}`)
    .eq("competition_code", selected.competition)
    .eq("season", selected.season)
    .not("home_goals_ft", "is", null)
    .order("kickoff_date", { ascending: false })
    .limit(8);
  const recent = (recentRes.data ?? []) as Fixture[];

  return (
    <div className="space-y-8">
      <Link href="/teams" className="text-sm text-muted transition hover:text-foreground">
        ← All teams
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{teamName}</h1>
        <p className="mt-1 text-sm text-muted">
          {COMPETITIONS[selected.competition] ?? selected.competition} ·{" "}
          {selected.season} · {overall?.matches ?? 0} matches ·{" "}
          {overall ? num(overall.points_per_game) : "—"} points per game
        </p>
      </header>

      {periods.length > 1 && (
        <nav className="flex flex-wrap gap-2">
          {periods.slice(0, 18).map((p) => {
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
        Counts of what happened in the matches this team played. They take no
        account of who the opponent was, so a high rate here says nothing on its
        own about the next fixture — the probabilities on a match page do that.
      </p>

      {(timing.length > 0 || first) && (
        <div className="grid gap-4 xl:grid-cols-2">
          <GoalTiming rows={timing} />
          {first && (
            <section className="overflow-hidden rounded-lg border border-border bg-surface">
              <header className="border-b border-border px-4 py-3">
                <h2 className="text-sm font-medium">Who scores first</h2>
                <p className="mt-0.5 text-xs text-muted">
                  Averaged over the matches it happened in, so a side that scores in
                  half its games is not credited with a goal in the rest.
                </p>
              </header>
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  <tr>
                    <td className="px-4 py-2">First goal scored</td>
                    <td className="tnum px-4 py-2 text-right text-xs text-muted">
                      in {first.matches_scored} of {first.matches}
                    </td>
                    <td className="tnum px-4 py-2 text-right font-medium">
                      {first.avg_first_scored ?? "—"}&apos;
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2">First goal conceded</td>
                    <td className="tnum px-4 py-2 text-right text-xs text-muted">
                      in {first.matches_conceded} of {first.matches}
                    </td>
                    <td className="tnum px-4 py-2 text-right font-medium">
                      {first.avg_first_conceded ?? "—"}&apos;
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2">Opened the scoring</td>
                    <td className="tnum px-4 py-2 text-right text-xs text-muted">
                      {first.scored_first} of {first.matches}
                    </td>
                    <td className="tnum px-4 py-2 text-right font-medium">
                      {Math.round((first.scored_first / first.matches) * 100)}%
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2">Failed to score</td>
                    <td className="tnum px-4 py-2 text-right text-xs text-muted">
                      {first.failed_to_score} of {first.matches}
                    </td>
                    <td className="tnum px-4 py-2 text-right font-medium">
                      {Math.round((first.failed_to_score / first.matches) * 100)}%
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
          )}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {GROUPS.map((group) => {
          const rows = linesFor(group.forMeasure);
          if (rows.length === 0) return null;
          return (
            <section
              key={group.title}
              className="overflow-hidden rounded-lg border border-border bg-surface"
            >
              <header className="border-b border-border px-4 py-3">
                <h2 className="text-sm font-medium">{group.title}</h2>
                <p className="mt-0.5 text-xs text-muted">
                  {measureAt(group.forMeasure, "overall")?.total ?? 0} in{" "}
                  {measureAt(group.forMeasure, "overall")?.matches ?? 0} matches
                </p>
              </header>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs uppercase tracking-widest text-muted">
                      <th className="px-4 py-2 text-left font-medium">Measure</th>
                      {VENUES.map((v) => (
                        <th key={v} className="px-4 py-2 text-right font-medium">
                          {VENUE_LABEL[v]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    <tr>
                      <td className="px-4 py-2">Per match</td>
                      {VENUES.map((v) => {
                        const m = measureAt(group.forMeasure, v);
                        return (
                          <td key={v} className="tnum px-4 py-2 text-right font-medium">
                            {m ? num(m.per_match) : "—"}
                          </td>
                        );
                      })}
                    </tr>
                    {measureAt(group.forMeasure, "overall")?.beat_opponent_rate !==
                      undefined &&
                      measureAt(group.forMeasure, "overall")?.beat_opponent_rate !==
                        null && (
                        <tr>
                          <td className="px-4 py-2">More than opponent</td>
                          {VENUES.map((v) => {
                            const rate =
                              measureAt(group.forMeasure, v)?.beat_opponent_rate ?? null;
                            return (
                              <td
                                key={v}
                                className={`tnum px-4 py-2 text-right font-medium ${heat(rate)}`}
                              >
                                {pct(rate)}
                              </td>
                            );
                          })}
                        </tr>
                      )}
                    {rows.map(({ line, byVenue }) => (
                      <tr key={line}>
                        <td className="px-4 py-2">
                          Over <span className="text-muted">{line}</span>
                        </td>
                        {VENUES.map((v) => {
                          const row = byVenue[v];
                          return (
                            <td
                              key={v}
                              className={`tnum px-4 py-2 text-right ${heat(
                                row ? row.over_rate : null
                              )}`}
                              title={
                                row
                                  ? `${row.over_count} of ${row.matches} matches`
                                  : undefined
                              }
                            >
                              {row ? pct(row.over_rate) : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                    {group.againstMeasure &&
                      linesFor(group.againstMeasure).length > 0 && (
                        <>
                          <tr className="bg-surface-raised">
                            <td
                              colSpan={4}
                              className="px-4 py-2 text-xs uppercase tracking-widest text-muted"
                            >
                              Conceded
                            </td>
                          </tr>
                          <tr>
                            <td className="px-4 py-2">Per match</td>
                            {VENUES.map((v) => {
                              const m = measureAt(group.againstMeasure!, v);
                              return (
                                <td
                                  key={v}
                                  className="tnum px-4 py-2 text-right font-medium"
                                >
                                  {m ? num(m.per_match) : "—"}
                                </td>
                              );
                            })}
                          </tr>
                          {linesFor(group.againstMeasure).map(({ line, byVenue }) => (
                            <tr key={`against-${line}`}>
                              <td className="px-4 py-2">
                                Over <span className="text-muted">{line}</span>
                              </td>
                              {VENUES.map((v) => {
                                const row = byVenue[v];
                                return (
                                  <td
                                    key={v}
                                    className={`tnum px-4 py-2 text-right ${heat(
                                      row ? row.over_rate : null
                                    )}`}
                                    title={
                                      row
                                        ? `${row.over_count} of ${row.matches} matches`
                                        : undefined
                                    }
                                  >
                                    {row ? pct(row.over_rate) : "—"}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </>
                      )}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
      </div>

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
