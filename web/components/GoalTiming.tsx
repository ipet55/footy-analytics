import type { TeamSeasonTiming } from "@/lib/types";

/** When a team scores and concedes, in fifteen-minute bands.
 *
 * Scored bars rise from the centre line and conceded fall from it, so the shape
 * of a season is one glance: a side that fades late has a heavy bottom-right and
 * a side that starts slowly has an empty top-left.
 *
 * Bars are scaled to the largest single band across both sides, not to each side
 * separately. Scaling them independently would make five conceded look the same
 * height as fifteen scored, which is the opposite of the comparison being made.
 */
const BANDS = ["1-15", "16-30", "31-45", "46-60", "61-75", "76-90"];

export function GoalTiming({ rows }: { rows: TeamSeasonTiming[] }) {
  if (rows.length === 0) return null;

  const scored = BANDS.map(
    (_, band) =>
      rows.find((r) => r.side === "for" && r.band === band)?.goals ?? 0
  );
  const conceded = BANDS.map(
    (_, band) =>
      rows.find((r) => r.side === "against" && r.band === band)?.goals ?? 0
  );
  const peak = Math.max(1, ...scored, ...conceded);
  const totalFor = scored.reduce((a, b) => a + b, 0);
  const totalAgainst = conceded.reduce((a, b) => a + b, 0);

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">When goals happen</h2>
        {/* The totals are stated because they do not match the goals table below,
            and a reader who spots that without explanation will assume one of the
            two is broken. Own goals belong to neither side's timing and extra time
            is not comparable with regulation, so both are left out here. */}
        <p className="mt-0.5 text-xs text-muted">
          {totalFor} scored and {totalAgainst} conceded in regulation, by
          fifteen-minute band. Added time counts in the band its minute falls in;
          own goals and extra time are excluded.
        </p>
      </header>
      <div className="px-4 py-4">
        <div className="flex items-end gap-2">
          {BANDS.map((label, band) => (
            <div key={label} className="flex flex-1 flex-col items-center gap-1">
              {/* Fixed height because an empty span collapses to nothing, and with
                  the columns bottom-aligned a band that conceded nothing would sit
                  lower than its neighbours and read as a different scale. */}
              <span className="tnum h-4 text-xs text-muted">
                {scored[band] || ""}
              </span>
              <div className="flex h-20 w-full items-end">
                <div
                  className="w-full rounded-t bg-accent"
                  style={{ height: `${(scored[band] / peak) * 100}%` }}
                />
              </div>
              <span className="border-t border-border pt-1 text-[10px] uppercase tracking-wider text-muted">
                {label}
              </span>
              <div className="flex h-20 w-full items-start">
                <div
                  className="w-full rounded-b bg-edge-negative/70"
                  style={{ height: `${(conceded[band] / peak) * 100}%` }}
                />
              </div>
              <span className="tnum h-4 text-xs text-muted">
                {conceded[band] || ""}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 flex justify-center gap-5 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-accent" />
            scored
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-edge-negative/70" />
            conceded
          </span>
        </div>
      </div>
    </section>
  );
}
