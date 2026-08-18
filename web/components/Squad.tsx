import { PlayerLink } from "@/components/PlayerLink";
import type { SquadPlayer } from "@/lib/types";

/** The club's current roster, grouped by line.
 *
 * "Current" is meant literally: this is who is at the club today, not who played
 * this season. A player sold in January is absent rather than listed as departed,
 * because the provider's endpoint has no season dimension and inventing one from
 * appearances would produce a different, quieter kind of wrong.
 *
 * Unavailability is shown inline rather than as a separate list. A squad with the
 * injured players struck through answers "who can play on Saturday" in one pass,
 * which is the question being asked.
 */
const LINES = ["Goalkeeper", "Defender", "Midfielder", "Attacker"] as const;

export function Squad({ players }: { players: SquadPlayer[] }) {
  if (players.length === 0) return null;

  const unavailable = players.filter((p) => p.absence_status !== null);

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium">Squad</h2>
          <span className="text-xs text-muted">{players.length} players</span>
        </div>
        <p className="mt-0.5 text-xs text-muted">
          Who is at the club now, not who played this season. Availability is for
          the next fixture and is only published within a few days of it
          {unavailable.length > 0
            ? `; ${unavailable.length} currently reported unavailable.`
            : "."}
        </p>
      </header>

      <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
        {LINES.map((line) => {
          const group = players
            .filter((p) => p.position === line)
            .sort((a, b) => (a.shirt_number ?? 999) - (b.shirt_number ?? 999));
          if (group.length === 0) return null;
          return (
            <div key={line} className="bg-surface px-4 py-3">
              <p className="text-[10px] uppercase tracking-widest text-muted">
                {line === "Attacker" ? "Attack" : line}
                <span className="ml-1.5 tnum">{group.length}</span>
              </p>
              <ul className="mt-1.5 space-y-1">
                {group.map((p) => (
                  <li
                    key={p.player_id}
                    className="flex items-center gap-2 text-sm"
                    title={
                      p.absence_reason
                        ? `${p.absence_reason} — ${p.absence_status}`
                        : undefined
                    }
                  >
                    <span className="tnum w-6 shrink-0 text-right text-xs text-muted">
                      {p.shirt_number ?? ""}
                    </span>
                    <PlayerLink
                      id={p.player_id}
                      name={p.player_name}
                      photo={p.photo_url}
                      strike={p.absence_status === "out"}
                      muted={p.absence_status === "doubtful"}
                    />
                    {p.absence_status && (
                      <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted">
                        {p.absence_status === "out" ? "out" : "?"}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      {unavailable.length > 0 && (
        <div className="border-t border-border px-4 py-3">
          <p className="text-[10px] uppercase tracking-widest text-muted">
            Reported unavailable
          </p>
          <ul className="mt-1.5 grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
            {unavailable.map((p) => (
              <li
                key={p.player_id}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <PlayerLink
                  id={p.player_id}
                  name={p.player_name}
                  photo={p.photo_url}
                />
                <span className="shrink-0 text-xs text-muted">
                  {p.absence_reason ?? "Unavailable"}
                  {p.absence_status === "doubtful" ? " · doubtful" : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
