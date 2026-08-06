import type { MarketPrice, Prediction } from "@/lib/types";

const SELECTION_LABEL: Record<string, string> = {
  home: "Home",
  draw: "Draw",
  away: "Away",
  over: "Over",
  under: "Under",
  yes: "Yes",
  no: "No",
};

function pct(p: number) {
  return `${(p * 100).toFixed(1)}%`;
}

/**
 * A market's rows, with the closing price beside ours where one exists.
 *
 * The gap between the two columns is the reason the page exists, so it gets its
 * own column rather than being left for the reader to subtract. It is shown in
 * percentage points and only when the market actually priced the thing: no book
 * in this database quotes corners, fouls or shots, and inventing a comparison
 * there would be worse than admitting there is none.
 */
export function MarketCard({
  title,
  subtitle,
  rows,
  prices,
  teamNames,
}: {
  title: string;
  subtitle?: string;
  rows: Prediction[];
  prices: MarketPrice[];
  teamNames?: { home: string; away: string };
}) {
  if (rows.length === 0) return null;

  const priceFor = (line: number | null, selection: string) =>
    prices.find(
      (p) =>
        (p.line === null ? null : Number(p.line)) ===
          (line === null ? null : Number(line)) && p.selection === selection,
    )?.probability;

  const hasAnyPrice = rows.some((r) => priceFor(r.line, r.selection) !== undefined);
  const settled = rows.some((r) => r.hit !== null);
  const observed = rows.find((r) => r.observed !== null)?.observed ?? null;

  const label = (r: Prediction) => {
    if (r.selection === "home" && teamNames) return teamNames.home;
    if (r.selection === "away" && teamNames) return teamNames.away;
    return SELECTION_LABEL[r.selection] ?? r.selection;
  };

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex items-baseline justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-medium">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
        {observed !== null && (
          <span className="tnum shrink-0 text-xs text-muted">
            actual <span className="text-foreground">{observed}</span>
          </span>
        )}
      </header>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wider text-muted">
            <th className="px-4 py-2 text-left font-medium">Selection</th>
            <th className="px-3 py-2 text-right font-medium">Model</th>
            {hasAnyPrice && (
              <>
                <th className="px-3 py-2 text-right font-medium">Market</th>
                <th className="px-3 py-2 text-right font-medium">Edge</th>
              </>
            )}
            {settled && <th className="px-4 py-2 text-right font-medium">Result</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {rows.map((r) => {
            const market = priceFor(r.line, r.selection);
            const edge = market === undefined ? null : r.probability - market;
            return (
              <tr key={`${r.line ?? "x"}-${r.selection}`}>
                <td className="px-4 py-2">
                  {label(r)}
                  {r.line !== null && (
                    <span className="tnum ml-1.5 text-muted">{Number(r.line)}</span>
                  )}
                </td>
                <td className="tnum px-3 py-2 text-right font-medium">
                  {pct(r.probability)}
                </td>
                {hasAnyPrice && (
                  <>
                    <td className="tnum px-3 py-2 text-right text-muted">
                      {market === undefined ? "—" : pct(market)}
                    </td>
                    <td
                      className={`tnum px-3 py-2 text-right ${
                        edge === null
                          ? "text-muted"
                          : Math.abs(edge) < 0.02
                            ? "text-muted"
                            : edge > 0
                              ? "text-edge-positive"
                              : "text-edge-negative"
                      }`}
                    >
                      {edge === null
                        ? "—"
                        : `${edge > 0 ? "+" : ""}${(edge * 100).toFixed(1)}`}
                    </td>
                  </>
                )}
                {settled && (
                  <td className="px-4 py-2 text-right">
                    {r.hit === null ? (
                      <span className="text-xs text-muted">pending</span>
                    ) : (
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs ${
                          r.hit
                            ? "bg-edge-positive/10 text-edge-positive"
                            : "bg-edge-negative/10 text-edge-negative"
                        }`}
                      >
                        {r.hit ? "hit" : "miss"}
                      </span>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
