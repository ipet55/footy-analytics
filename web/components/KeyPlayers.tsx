import { PlayerLink } from "@/components/PlayerLink";
import type { KeyPlayer } from "@/lib/types";

/** The six names a reader looks for first.
 *
 * Ranked by what they have done for this club in the last two seasons —
 * goals and assists first, then minutes — so a striker who plays less than
 * a full-back still sits above him when he is the reason the attack rating
 * exists. The ranking is a description, not a model coefficient.
 */
export function KeyPlayers({ players }: { players: KeyPlayer[] }) {
  const top = players.filter((p) => p.rank <= 6).slice(0, 6);
  if (top.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Key players</h2>
        <p className="mt-0.5 text-xs text-muted">
          Who has contributed most for this club across the last two seasons.
          When one of them is reported out, the match probabilities move.
        </p>
      </header>
      <ul className="divide-y divide-border">
        {top.map((p) => (
          <li
            key={p.player_id}
            className="flex items-center justify-between gap-3 px-4 py-2.5"
          >
            <div className="flex min-w-0 items-center gap-3">
              <span className="tnum w-4 shrink-0 text-xs text-muted">
                {p.rank}
              </span>
              <PlayerLink
                id={p.player_id}
                name={p.player_name}
                photo={p.photo_url}
                size={32}
              />
            </div>
            <span className="shrink-0 text-xs text-muted">
              {p.goals > 0 || p.assists > 0 ? (
                <>
                  <span className="tnum font-medium text-foreground">
                    {p.goals}
                  </span>
                  {p.assists > 0 && (
                    <>
                      <span className="mx-0.5">+</span>
                      <span className="tnum">{p.assists}</span>
                    </>
                  )}
                  <span className="ml-1">
                    {p.goals === 1 && p.assists === 0 ? "goal" : "g/a"}
                  </span>
                </>
              ) : (
                <span className="tnum">{p.minutes}&apos;</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
