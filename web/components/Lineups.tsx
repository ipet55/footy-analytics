import type { MatchLineup } from "@/lib/types";

/** Both team sheets side by side: the eleven, the bench, the formation, the coach.
 *
 * Grouped by line — keeper, defence, midfield, attack — because that is how a
 * sheet is read, and a flat list of eleven names in shirt-number order tells you
 * nothing about the shape. Where the feed gives no position the players fall into
 * a single unlabelled group rather than being forced into a guessed line.
 */
const LINES: { key: string; label: string }[] = [
  { key: "G", label: "Goalkeeper" },
  { key: "D", label: "Defence" },
  { key: "M", label: "Midfield" },
  { key: "F", label: "Attack" },
];

function Sheet({ rows, label }: { rows: MatchLineup[]; label: string }) {
  const starters = rows.filter((r) => r.is_starter);
  const bench = rows.filter((r) => !r.is_starter);
  const formation = rows.find((r) => r.formation)?.formation;
  const coach = rows.find((r) => r.coach_name)?.coach_name;
  const positioned = starters.some((r) => r.position);

  const group = (key: string) =>
    starters
      .filter((r) => r.position === key)
      .sort((a, b) => (a.shirt_number ?? 99) - (b.shirt_number ?? 99));

  const Player = ({ r }: { r: MatchLineup }) => (
    <li className="flex items-baseline gap-2 py-0.5 text-sm">
      <span className="tnum w-6 shrink-0 text-right text-xs text-muted">
        {r.shirt_number ?? ""}
      </span>
      <span className="truncate">{r.player_name}</span>
    </li>
  );

  return (
    <div className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{label}</h3>
        {formation && <span className="tnum text-xs text-muted">{formation}</span>}
      </div>
      {coach && <p className="mt-0.5 text-xs text-muted">Coach: {coach}</p>}

      <div className="mt-3 space-y-3">
        {positioned ? (
          LINES.map(({ key, label: line }) => {
            const players = group(key);
            if (players.length === 0) return null;
            return (
              <div key={key}>
                <p className="text-[10px] uppercase tracking-widest text-muted">
                  {line}
                </p>
                <ul className="mt-0.5">
                  {players.map((r) => (
                    <Player key={r.player_name} r={r} />
                  ))}
                </ul>
              </div>
            );
          })
        ) : (
          <ul>
            {starters
              .sort((a, b) => (a.shirt_number ?? 99) - (b.shirt_number ?? 99))
              .map((r) => (
                <Player key={r.player_name} r={r} />
              ))}
          </ul>
        )}
      </div>

      {bench.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="text-[10px] uppercase tracking-widest text-muted">
            Substitutes
          </p>
          <ul className="mt-0.5">
            {bench
              .sort((a, b) => (a.shirt_number ?? 99) - (b.shirt_number ?? 99))
              .map((r) => (
                <li
                  key={r.player_name}
                  className="flex items-baseline gap-2 py-0.5 text-sm text-muted"
                >
                  <span className="tnum w-6 shrink-0 text-right text-xs">
                    {r.shirt_number ?? ""}
                  </span>
                  <span className="truncate">{r.player_name}</span>
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Lineups({
  rows,
  homeTeam,
  awayTeam,
}: {
  rows: MatchLineup[];
  homeTeam: string;
  awayTeam: string;
}) {
  if (rows.length === 0) return null;
  const home = rows.filter((r) => r.is_home);
  const away = rows.filter((r) => !r.is_home);
  if (home.length === 0 || away.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Team sheets</h2>
        <p className="mt-0.5 text-xs text-muted">
          The confirmed elevens, which the feed publishes about an hour before
          kickoff.
        </p>
      </header>
      <div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
        <Sheet rows={home} label={homeTeam} />
        <Sheet rows={away} label={awayTeam} />
      </div>
    </section>
  );
}
