import type { MatchAbsence, MatchEffect, Prediction, TeamForm } from "@/lib/types";

/** The model's read on a match, in sentences.
 *
 * Everything here is derived from the stored probabilities — nothing is generated,
 * nothing is invented, and every claim traces to a number on the page below. The
 * point is to answer "how do you think this goes" without making the reader
 * assemble it from seventy rows of a probability table.
 *
 * The tone is deliberately hedged, because the model is well calibrated and does
 * not beat the market. A 65% favourite loses more than a third of the time and the
 * writing has to keep saying so, or the page promises something it cannot deliver.
 */

/** An over/under ladder is a survival function, so consecutive differences give
 *  the distribution over counts. P(exactly 1) is P(over 0.5) − P(over 1.5). The
 *  final bucket stays open — "3 or more" — because there is no line above it. */
function distribution(rows: Prediction[], market: string) {
  const overs = rows
    .filter((r) => r.market_code === market && r.selection === "over" && r.line !== null)
    .map((r) => ({ line: Number(r.line), p: Number(r.probability) }))
    .sort((a, b) => a.line - b.line);
  if (overs.length === 0) return null;

  const buckets: number[] = [1 - overs[0].p];
  for (let i = 0; i < overs.length - 1; i += 1) {
    buckets.push(overs[i].p - overs[i + 1].p);
  }
  const openFrom = overs.length;
  return { buckets, openTail: overs[overs.length - 1].p, openFrom };
}

/** The most likely exact count, with how likely it is.
 *
 * Only closed buckets are candidates. The open tail is often the largest single
 * category — a side expected to score 1.7 goals has "three or more" ahead of any
 * exact number — but "3 or more" is not a scoreline, so it cannot be the answer
 * to what the score will be.
 */
function likeliest(market: string, rows: Prediction[]) {
  const dist = distribution(rows, market);
  if (!dist) return null;
  const best = Math.max(...dist.buckets);
  return { goals: dist.buckets.indexOf(best), p: best };
}

function pct(p: number) {
  return `${Math.round(p * 100)}%`;
}

/** Plain-language labels. A reader should never have to decode "shots_home". */
function describe(r: Prediction, home: string, away: string): string | null {
  const line = r.line === null ? null : Number(r.line);
  const side = r.selection === "over" ? "over" : "under";
  const noun: Record<string, string> = {
    goals_total: "goals in the match",
    goals_home: `${home} goals`,
    goals_away: `${away} goals`,
    corners_home: `${home} corners`,
    corners_away: `${away} corners`,
    corners_total: "corners in the match",
    shots_total: "shots in the match",
    shots_home: `${home} shots`,
    shots_away: `${away} shots`,
    fouls_total: "fouls in the match",
    cards_total: "cards in the match",
  };
  if (r.market_code === "goals_btts") {
    return r.selection === "yes" ? "both teams to score" : "at least one clean sheet";
  }
  const label = noun[r.market_code];
  if (!label || line === null) return null;
  return `${side} ${line} ${label}`;
}

export function Preview({
  predictions,
  absences,
  effects,
  form,
  homeTeam,
  awayTeam,
}: {
  predictions: Prediction[];
  absences: MatchAbsence[];
  effects: MatchEffect[];
  form: TeamForm[];
  homeTeam: string;
  awayTeam: string;
}) {
  const outcome = predictions.filter((p) => p.market_code === "goals_1x2");
  if (outcome.length === 0) return null;

  const byPick = Object.fromEntries(
    outcome.map((p) => [p.selection, Number(p.probability)])
  ) as Record<string, number>;
  const ranked = [...outcome].sort(
    (a, b) => Number(b.probability) - Number(a.probability)
  );
  const top = ranked[0];
  const topLabel =
    top.selection === "home"
      ? `${homeTeam} to win`
      : top.selection === "away"
        ? `${awayTeam} to win`
        : "a draw";

  const homeGoals = likeliest("goals_home", predictions);
  const awayGoals = likeliest("goals_away", predictions);

  // The strongest statements the model is willing to make. Ordered by confidence
  // and capped, because a list of thirty is a table again — and 1X2 is excluded
  // since it already leads the paragraph above.
  const calls = predictions
    .filter(
      (p) =>
        p.market_code !== "goals_1x2" &&
        Number(p.probability) >= 0.7 &&
        describe(p, homeTeam, awayTeam) !== null
    )
    .sort((a, b) => Number(b.probability) - Number(a.probability))
    .slice(0, 6);

  const homeOut = absences.filter((a) => a.is_home && a.status === "out").length;
  const awayOut = absences.filter((a) => !a.is_home && a.status === "out").length;

  const homeForm = form.find((f) => f.is_home);
  const awayForm = form.find((f) => !f.is_home);

  const margin = byPick.home - byPick.away;
  const shape =
    Math.abs(margin) < 0.1
      ? "The model sees very little between these two."
      : Math.abs(margin) < 0.25
        ? "The model leans one way without much conviction."
        : "The model sees a clear favourite.";

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">How the model sees it</h2>
        <p className="mt-0.5 text-xs text-muted">
          Written from the probabilities below, not in addition to them. Every
          statement here is one of those numbers in words.
        </p>
      </header>

      <div className="space-y-3 px-4 py-4 text-sm leading-relaxed">
        <p>
          {shape} <span className="font-medium">{topLabel}</span> is the most
          likely single outcome at {pct(Number(top.probability))}, against{" "}
          {pct(byPick.draw)} for a draw and{" "}
          {pct(top.selection === "home" ? byPick.away : byPick.home)} for{" "}
          {top.selection === "home" ? awayTeam : homeTeam}.
          {Number(top.probability) < 0.5 &&
            " Note that this is still under a half — the other two results together are more likely than the favourite."}
        </p>

        {homeGoals && awayGoals && (
          <p>
            The most likely scoreline is{" "}
            <span className="font-medium tnum">
              {homeGoals.goals}–{awayGoals.goals}
            </span>
            , at roughly {pct(homeGoals.p * awayGoals.p)}. That is the point of a
            scoreline rather than a caveat on it — the single likeliest result of a
            football match is usually somewhere near one chance in eight, so the
            other seven matter more. It is read off the goals markets rather than
            predicted directly, and treats the two sides as independent, which they
            very slightly are not.
          </p>
        )}

        {calls.length > 0 && (
          <div>
            <p className="text-muted">
              Where the model is most confident, in order:
            </p>
            <ul className="mt-1.5 space-y-1">
              {calls.map((c) => (
                <li
                  key={`${c.market_code}-${c.line}-${c.selection}`}
                  className="flex items-baseline justify-between gap-3"
                >
                  <span>{describe(c, homeTeam, awayTeam)}</span>
                  <span className="tnum shrink-0 font-medium">
                    {pct(Number(c.probability))}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <AbsenceNote
          effects={effects}
          absences={absences}
          predictions={predictions}
          homeTeam={homeTeam}
          awayTeam={awayTeam}
          homeOut={homeOut}
          awayOut={awayOut}
        />

        {homeForm?.gf_10 != null &&
          homeForm.ga_10 != null &&
          awayForm?.gf_10 != null &&
          awayForm.ga_10 != null && (
            <p className="text-muted">
              Over their previous ten matches {homeTeam} averaged{" "}
              {Number(homeForm.gf_10).toFixed(2)} scored and{" "}
              {Number(homeForm.ga_10).toFixed(2)} conceded, {awayTeam}{" "}
              {Number(awayForm.gf_10).toFixed(2)} and{" "}
              {Number(awayForm.ga_10).toFixed(2)}. Both were knowable before
              kickoff.
            </p>
          )}
      </div>
    </section>
  );
}

function AbsenceNote({
  effects,
  absences,
  predictions,
  homeTeam,
  awayTeam,
  homeOut,
  awayOut,
}: {
  effects: MatchEffect[];
  absences: MatchAbsence[];
  predictions: Prediction[];
  homeTeam: string;
  awayTeam: string;
  homeOut: number;
  awayOut: number;
}) {
  if (homeOut === 0 && awayOut === 0 && effects.length === 0) return null;

  const names = (isHome: boolean) => {
    const fromEffect = effects
      .filter((e) => e.is_home === isHome)
      .flatMap((e) => e.detail.filter((d) => d.is_key).map((d) => d.player_name));
    if (fromEffect.length > 0) return fromEffect;
    return absences
      .filter((a) => a.is_home === isHome && a.status === "out")
      .map((a) => a.player_name);
  };
  const homeNames = names(true);
  const awayNames = names(false);

  const base = effects.find((e) => e.p_home_base != null);
  const now = Object.fromEntries(
    predictions
      .filter((p) => p.market_code === "goals_1x2")
      .map((p) => [p.selection, Number(p.probability)])
  ) as Record<string, number>;

  const moved =
    base &&
    base.p_home_base != null &&
    now.home != null &&
    Math.abs(now.home - Number(base.p_home_base)) >= 0.01;

  const side = (label: string, count: number, who: string[]) => {
    if (count === 0) return null;
    const listed = who.slice(0, 3).join(", ");
    return `${label} are without ${count} player${count === 1 ? "" : "s"}${
      listed ? ` (${listed}${who.length > 3 ? "…" : ""})` : ""
    }`;
  };

  return (
    <p className="text-muted">
      {side(homeTeam, homeOut, homeNames)}
      {homeOut > 0 && awayOut > 0 && " and "}
      {side(awayTeam, awayOut, awayNames)}
      {moved && base ? (
        <>
          . Those absences are in the percentages: {homeTeam} to win moved from{" "}
          {pct(Number(base.p_home_base))} to {pct(now.home)}
          {now.away != null && base.p_away_base != null && (
            <>
              , {awayTeam} from {pct(Number(base.p_away_base))} to {pct(now.away)}
            </>
          )}
          .
        </>
      ) : effects.length > 0 ? (
        ". Those absences are already folded into the percentages above."
      ) : (
        ". No key player among them, so the percentages did not move."
      )}
    </p>
  );
}
