import type { ExpectedPlayer } from "@/lib/types";

/** The likely eleven, for the hours before the real one is published.
 *
 * This is a guess and is labelled as one throughout. It is who has been starting
 * lately, minus anyone reported out — no formation is solved for, because ranking
 * by starts cannot tell a full-back from a centre-half and a tidier answer would
 * not be a truer one.
 *
 * A side with no team sheets in the last ten matches simply does not appear. A
 * promoted club has no history in a competition we cover, and eleven names picked
 * from nothing would be the worst thing this page could show.
 */
const ORDER: Record<string, number> = { G: 0, D: 1, M: 2, F: 3 };

function Side({ rows, team }: { rows: ExpectedPlayer[]; team: string }) {
  if (rows.length === 0) {
    return (
      <div className="px-4 py-3">
        <h3 className="text-sm font-medium">{team}</h3>
        <p className="mt-2 text-sm text-muted">
          No recent team sheets to project from.
        </p>
      </div>
    );
  }

  const xi = rows
    .filter((r) => r.expected_to_start)
    .sort(
      (a, b) =>
        (ORDER[a.position ?? ""] ?? 4) - (ORDER[b.position ?? ""] ?? 4) ||
        b.starts - a.starts
    );
  const bench = rows
    .filter((r) => !r.expected_to_start)
    .sort((a, b) => b.starts - a.starts)
    .slice(0, 7);

  return (
    <div className="px-4 py-3">
      <h3 className="text-sm font-medium">{team}</h3>
      <ul className="mt-2 space-y-0.5">
        {xi.map((r) => (
          <li
            key={r.player_name}
            className="flex items-baseline gap-2 text-sm"
            title={r.absence_reason ?? undefined}
          >
            <span className="tnum w-6 shrink-0 text-right text-xs text-muted">
              {r.shirt_number ?? ""}
            </span>
            <span
              className={`min-w-0 flex-1 truncate ${
                r.absence_status === "doubtful" ? "text-muted" : ""
              }`}
            >
              {r.player_name}
              {r.absence_status === "doubtful" && (
                <span className="ml-1.5 text-[10px] uppercase tracking-wider">
                  doubt
                </span>
              )}
            </span>
            <span className="tnum shrink-0 text-xs text-muted">
              {r.starts}/{r.named}
            </span>
          </li>
        ))}
      </ul>
      {bench.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="text-[10px] uppercase tracking-widest text-muted">
            Next in line
          </p>
          <p className="mt-1 text-sm text-muted">
            {bench.map((r) => r.player_name).join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}

export function ExpectedXI({
  rows,
  homeTeam,
  awayTeam,
}: {
  rows: ExpectedPlayer[];
  homeTeam: string;
  awayTeam: string;
}) {
  if (rows.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Expected eleven</h2>
        <p className="mt-0.5 text-xs text-muted">
          A projection, not a team sheet: who has started most of the last ten
          matches, minus anyone reported out. The figures are starts out of
          appearances in the squad. The confirmed elevens replace this about an
          hour before kickoff.
        </p>
      </header>
      <div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
        <Side rows={rows.filter((r) => r.is_home)} team={homeTeam} />
        <Side rows={rows.filter((r) => !r.is_home)} team={awayTeam} />
      </div>
    </section>
  );
}
