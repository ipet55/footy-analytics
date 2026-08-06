import { supabase } from "@/lib/supabase";

export const revalidate = 300;

type Accuracy = {
  market_code: string;
  line: number | null;
  selection: string;
  settled: number;
  avg_predicted: number;
  actual_rate: number;
  bias: number;
};

const TITLES: Record<string, string> = {
  goals_1x2: "Match result",
  goals_total: "Total goals",
  goals_btts: "Both teams to score",
  goals_home: "Home team goals",
  goals_away: "Away team goals",
  corners_home: "Home corners",
  corners_away: "Away corners",
  shots_total: "Total shots",
  fouls_total: "Total fouls",
};

export default async function AccuracyPage() {
  const { data, error } = await supabase
    .from("market_accuracy")
    .select("*")
    .order("market_code")
    .order("line")
    .order("selection");

  if (error) {
    return (
      <div className="rounded-lg border border-edge-negative/40 bg-edge-negative/5 p-4 text-sm">
        Could not load the track record: {error.message}
      </div>
    );
  }

  const rows = (data ?? []) as Accuracy[];
  const byMarket = new Map<string, Accuracy[]>();
  for (const r of rows) {
    const list = byMarket.get(r.market_code) ?? [];
    list.push(r);
    byMarket.set(r.market_code, list);
  }

  const totalSettled = rows.reduce((sum, r) => sum + Number(r.settled), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Track record</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          What the model said against what happened, over {totalSettled.toLocaleString()}{" "}
          settled predictions. A well-calibrated market has the two columns close
          together: if we say 60% to a hundred fixtures, roughly sixty should land.
          Bias is the gap in percentage points, positive where the model was too
          low. Small samples move these numbers a lot, so the count matters as much
          as the gap.
        </p>
      </div>

      <div className="space-y-4">
        {[...byMarket.entries()].map(([code, group]) => (
          <section
            key={code}
            className="overflow-hidden rounded-lg border border-border bg-surface"
          >
            <header className="border-b border-border px-4 py-3">
              <h2 className="text-sm font-medium">{TITLES[code] ?? code}</h2>
            </header>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wider text-muted">
                  <th className="px-4 py-2 text-left font-medium">Selection</th>
                  <th className="px-3 py-2 text-right font-medium">Predicted</th>
                  <th className="px-3 py-2 text-right font-medium">Actual</th>
                  <th className="px-3 py-2 text-right font-medium">Bias</th>
                  <th className="px-4 py-2 text-right font-medium">n</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {group.map((r) => (
                  <tr key={`${r.line ?? "x"}-${r.selection}`}>
                    <td className="px-4 py-2">
                      {r.selection}
                      {r.line !== null && (
                        <span className="tnum ml-1.5 text-muted">
                          {Number(r.line)}
                        </span>
                      )}
                    </td>
                    <td className="tnum px-3 py-2 text-right">
                      {(Number(r.avg_predicted) * 100).toFixed(1)}%
                    </td>
                    <td className="tnum px-3 py-2 text-right">
                      {(Number(r.actual_rate) * 100).toFixed(1)}%
                    </td>
                    <td
                      className={`tnum px-3 py-2 text-right ${
                        Math.abs(Number(r.bias)) < 0.05
                          ? "text-muted"
                          : Number(r.bias) > 0
                            ? "text-edge-positive"
                            : "text-edge-negative"
                      }`}
                    >
                      {Number(r.bias) > 0 ? "+" : ""}
                      {(Number(r.bias) * 100).toFixed(1)}
                    </td>
                    <td className="tnum px-4 py-2 text-right text-muted">
                      {r.settled}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>
    </div>
  );
}
