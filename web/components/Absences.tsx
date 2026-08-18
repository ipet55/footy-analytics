import { PlayerLink } from "@/components/PlayerLink";
import type { MatchAbsence } from "@/lib/types";

/** Who misses this match, and why, for both sides.
 *
 * Definite absences lead and doubtful ones follow, because a manager's problem is
 * ordered that way and so is a reader's question. The reason is the provider's own
 * wording rather than a category of ours — "Ribs Injury" is more useful than
 * "injured", and inventing buckets over an open vocabulary means putting things in
 * the wrong one.
 *
 * Silence here means the provider has published nothing, which is the normal state
 * until about three days before kickoff. That is worth saying on the page: an empty
 * list otherwise reads as a fully fit squad.
 */
function Side({ rows, team }: { rows: MatchAbsence[]; team: string }) {
  const out = rows.filter((r) => r.status === "out");
  const doubtful = rows.filter((r) => r.status === "doubtful");

  return (
    <div className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{team}</h3>
        <span className="text-xs text-muted">
          {out.length} out
          {doubtful.length > 0 && `, ${doubtful.length} doubtful`}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Nothing reported.</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {[...out, ...doubtful].map((r) => (
            <li
              key={r.player_id ?? r.player_name}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <PlayerLink
                id={r.player_id}
                name={r.player_name}
                photo={r.photo_url}
                muted={r.status === "doubtful"}
              />
              <span className="shrink-0 text-xs text-muted">
                {r.reason ?? (r.status === "out" ? "Unavailable" : "Doubtful")}
                {r.status === "doubtful" && r.reason ? " · doubtful" : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Absences({
  rows,
  homeTeam,
  awayTeam,
  played,
}: {
  rows: MatchAbsence[];
  homeTeam: string;
  awayTeam: string;
  played: boolean;
}) {
  // After the fact the team sheets say who actually played, which is better
  // evidence than a pre-match doubt, so this only earns space beforehand.
  if (played || rows.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Team news</h2>
        <p className="mt-0.5 text-xs text-muted">
          Injuries and suspensions reported for this fixture. Published from about
          three days before kickoff, so an empty side means nothing has been
          reported rather than everyone being fit. Key absences are already
          folded into the probabilities above.
        </p>
      </header>
      <div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
        <Side rows={rows.filter((r) => r.is_home)} team={homeTeam} />
        <Side rows={rows.filter((r) => !r.is_home)} team={awayTeam} />
      </div>
    </section>
  );
}
