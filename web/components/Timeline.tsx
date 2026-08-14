import type { MatchEvent } from "@/lib/types";

/** Goals, cards and substitutions in the order they happened.
 *
 * Home events lean left and away right, so the shape of a match is readable
 * before any of it is: a cluster on one side is a spell of pressure.
 *
 * Substitutions are included but muted. They are the bulk of the events and the
 * least interesting individually, yet leaving them out makes a match look emptier
 * than it was and hides the hour when a manager changed something.
 */
const LABEL: Record<string, string> = {
  goal: "Goal",
  card: "Card",
  substitution: "Substitution",
  var: "VAR",
  other: "Event",
};

function minuteOf(e: MatchEvent) {
  return e.extra_minute ? `${e.minute}+${e.extra_minute}` : `${e.minute}`;
}

/** Own goals are attributed by the feed to the player who scored them, so the
 *  team on the row is not the team that benefited. Saying so avoids a scoreline
 *  that appears not to add up. */
function describe(e: MatchEvent) {
  const detail = e.detail ?? LABEL[e.kind];
  if (e.kind === "goal") {
    if (e.detail === "Own Goal") return "Own goal";
    return e.assist_name ? `Goal, assist ${e.assist_name}` : detail;
  }
  return detail;
}

function tone(e: MatchEvent) {
  if (e.kind === "goal") return "text-foreground font-medium";
  if (e.detail === "Red Card" || e.detail === "Second Yellow card") {
    return "text-edge-negative";
  }
  if (e.kind === "card") return "text-muted";
  return "text-muted opacity-70";
}

export function Timeline({
  events,
  homeGoals,
  awayGoals,
}: {
  events: MatchEvent[];
  homeGoals?: number | null;
  awayGoals?: number | null;
}) {
  if (events.length === 0) return null;

  const ordered = [...events].sort(
    (a, b) =>
      a.minute - b.minute || (a.extra_minute ?? 0) - (b.extra_minute ?? 0)
  );

  // The feed reports extra time and penalty shootouts as ordinary goal events, so
  // a tie decided on penalties shows six goals for a match recorded as 0-3. Count
  // regulation goals and say plainly when they disagree with the score, rather
  // than leaving a reader to wonder which of the two is lying.
  const regulation = ordered.filter(
    (e) => e.kind === "goal" && e.minute <= 90 && e.detail !== "Own Goal"
  );
  const countedHome = regulation.filter((e) => e.is_home).length;
  const countedAway = regulation.filter((e) => !e.is_home).length;
  const known = homeGoals !== null && homeGoals !== undefined
    && awayGoals !== null && awayGoals !== undefined;
  const disagrees = known && (countedHome !== homeGoals || countedAway !== awayGoals);
  const beyond90 = ordered.some((e) => e.minute > 90);

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Timeline</h2>
        <p className="mt-0.5 text-xs text-muted">
          Home on the left, away on the right, in the order they happened.
          {beyond90 && " This match went past 90 minutes."}
        </p>
        {disagrees && (
          <p className="mt-1.5 text-xs text-edge-negative">
            The timeline records {countedHome}–{countedAway} in regulation against a
            result of {homeGoals}–{awayGoals}. Extra time, shootouts and disallowed
            goals all arrive here as ordinary events, so the result is the number to
            trust.
          </p>
        )}
      </header>
      <ul className="divide-y divide-border">
        {ordered.map((e, i) => (
          <li
            key={`${e.minute}-${e.extra_minute ?? 0}-${e.player_name ?? i}-${e.kind}`}
            className="grid grid-cols-[1fr_auto_1fr] items-baseline gap-3 px-4 py-2"
          >
            <span className={`min-w-0 truncate text-right text-sm ${tone(e)}`}>
              {e.is_home && (
                <>
                  {e.player_name ?? "—"}
                  <span className="ml-2 text-xs text-muted">{describe(e)}</span>
                </>
              )}
            </span>
            <span className="tnum w-12 text-center text-xs text-muted">
              {minuteOf(e)}&apos;
            </span>
            <span className={`min-w-0 truncate text-sm ${tone(e)}`}>
              {!e.is_home && (
                <>
                  {e.player_name ?? "—"}
                  <span className="ml-2 text-xs text-muted">{describe(e)}</span>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
