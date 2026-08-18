import type { Transfer } from "@/lib/types";

/** Ins and outs, this window.
 *
 * Split into two columns rather than one dated list, because the question is
 * almost always "who did they sign" or "who did they lose", and a merged list
 * makes the reader do the sorting.
 *
 * Loan returns are included and marked. They are noise on a transfer page in one
 * sense — nobody signed anybody — and they are the reason a squad suddenly has
 * four more names in it, so hiding them makes the squad list look wrong.
 */
function label(kind: string | null) {
  if (!kind || kind === "N/A") return null;
  // The provider spells this two ways and puts fees in the same field.
  if (kind === "Back from Loan" || kind === "Return from loan") return "loan return";
  return kind.toLowerCase();
}

function Column({
  rows,
  heading,
}: {
  rows: Transfer[];
  heading: string;
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">{heading}</h3>
        <span className="tnum text-xs text-muted">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">None in this window.</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {rows.map((t) => (
            <li key={t.transfer_id} className="text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate">{t.player_name}</span>
                <span className="shrink-0 text-xs text-muted">
                  {t.other_club ?? "—"}
                </span>
              </div>
              {label(t.kind) && (
                <span className="text-[10px] uppercase tracking-wider text-muted">
                  {label(t.kind)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Transfers({
  rows,
  since,
}: {
  rows: Transfer[];
  since: string;
}) {
  if (rows.length === 0) return null;
  const inbound = rows.filter((r) => r.direction === "in");
  const outbound = rows.filter((r) => r.direction === "out");

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium">Transfers</h2>
        <p className="mt-0.5 text-xs text-muted">
          Movement since {since}. Loan returns are included and marked, because
          they are why a squad gains names without anyone being signed.
        </p>
      </header>
      <div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
        <Column rows={inbound} heading="In" />
        <Column rows={outbound} heading="Out" />
      </div>
    </section>
  );
}
