/** One statistic, both teams, with the split shown as a bar.
 *
 * A bar rather than two numbers because the comparison is the whole point: 14
 * shots against 9 says something that 14 alone does not. The bar is proportional
 * to each side's share, so a lopsided row is visible before it is read.
 *
 * Renders nothing when either side is missing. Half a comparison is worse than
 * none — a reader shown "14 shots" against a blank will read the blank as zero.
 */
export function StatBar({
  label,
  home,
  away,
  suffix = "",
  decimals = 0,
}: {
  label: string;
  home: number | null | undefined;
  away: number | null | undefined;
  suffix?: string;
  decimals?: number;
}) {
  if (home === null || home === undefined || away === null || away === undefined) {
    return null;
  }
  const h = Number(home);
  const a = Number(away);
  const total = h + a;
  // A goalless, shotless row would divide by zero; split it evenly instead.
  const homeShare = total > 0 ? (h / total) * 100 : 50;

  const format = (v: number) => v.toFixed(decimals) + suffix;
  const leader = h === a ? "draw" : h > a ? "home" : "away";

  return (
    <div className="px-4 py-2.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className={`tnum ${leader === "home" ? "font-medium" : "text-muted"}`}>
          {format(h)}
        </span>
        <span className="text-xs uppercase tracking-widest text-muted">{label}</span>
        <span className={`tnum ${leader === "away" ? "font-medium" : "text-muted"}`}>
          {format(a)}
        </span>
      </div>
      <div className="mt-1.5 flex h-1 overflow-hidden rounded-full bg-surface-raised">
        <div
          className={leader === "home" ? "bg-accent" : "bg-border"}
          style={{ width: `${homeShare}%` }}
        />
        <div
          className={leader === "away" ? "bg-accent" : "bg-border"}
          style={{ width: `${100 - homeShare}%` }}
        />
      </div>
    </div>
  );
}
