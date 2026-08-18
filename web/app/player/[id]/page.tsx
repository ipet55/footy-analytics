import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/Badge";
import { Flag } from "@/components/Flag";
import { Photo } from "@/components/Photo";
import { supabase } from "@/lib/supabase";
import { COMPETITIONS, type Player, type PlayerSeasonStat } from "@/lib/types";

export const revalidate = 300;

const CUPS = new Set(["INT-UCL", "INT-UEL"]);

function num(value: number | null) {
  return value === null ? "—" : value;
}

function per90(total: number | null, minutes: number) {
  if (total === null || minutes <= 0) return "—";
  return ((total * 90) / minutes).toFixed(2);
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const playerId = Number(id);
  if (!Number.isFinite(playerId)) notFound();

  const [playerRes, statRes] = await Promise.all([
    supabase.from("player").select("*").eq("player_id", playerId).maybeSingle(),
    supabase
      .from("player_season_stat")
      .select("*")
      .eq("player_id", playerId)
      .order("start_year", { ascending: false }),
  ]);

  const player = playerRes.data as Player | null;
  const stats = (statRes.data ?? []) as PlayerSeasonStat[];
  if (!player && stats.length === 0) notFound();

  const name = player?.player_name ?? "Player";
  const photo = player?.photo_url ?? null;

  const periods = [
    ...new Map(
      stats.map((s) => [
        `${s.competition_code}|${s.season}`,
        {
          competition: s.competition_code,
          season: s.season,
          year: s.start_year,
        },
      ])
    ).values(),
  ].sort(
    (a, b) =>
      b.year - a.year ||
      Number(CUPS.has(a.competition)) - Number(CUPS.has(b.competition)) ||
      a.competition.localeCompare(b.competition)
  );

  return (
    <div className="space-y-8">
      <Link href="/teams" className="text-sm text-muted transition hover:text-foreground">
        ← Teams
      </Link>

      <header className="flex items-center gap-4">
        <Photo src={photo} name={name} size={72} />
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            {player?.team && player.team_id ? (
              <Link
                href={`/team/${player.team_id}`}
                className="inline-flex items-center gap-1.5 text-foreground transition hover:text-accent"
              >
                <Badge src={player.team_logo_url} name={player.team} size={18} />
                {player.team}
              </Link>
            ) : (
              <span>No current club in the squads we hold</span>
            )}
            {player?.position && <span>· {player.position}</span>}
            {player?.shirt_number != null && (
              <span className="tnum">· #{player.shirt_number}</span>
            )}
            {player?.age != null && <span className="tnum">· {player.age}</span>}
          </p>
        </div>
      </header>

      {stats.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
          No match statistics stored for this player yet. Appearances land as
          team sheets are loaded; a newly signed player will be empty until he
          plays.
        </p>
      ) : (
        <div className="space-y-6">
          {periods.map((period) => {
            const rows = stats.filter(
              (s) =>
                s.competition_code === period.competition &&
                s.season === period.season
            );
            return (
              <section
                key={`${period.competition}|${period.season}`}
                className="overflow-hidden rounded-lg border border-border bg-surface"
              >
                <header className="flex items-center gap-2 border-b border-border px-4 py-3">
                  <Flag competition={period.competition} size={14} />
                  <h2 className="text-sm font-medium">
                    {COMPETITIONS[period.competition] ?? period.competition}
                  </h2>
                  <span className="text-xs text-muted">{period.season}</span>
                </header>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs uppercase tracking-widest text-muted">
                        <th className="px-4 py-2 text-left font-medium">Club</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Apps</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Starts</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Min</th>
                        <th className="tnum px-3 py-2 text-right font-medium">G</th>
                        <th className="tnum px-3 py-2 text-right font-medium">A</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Shots</th>
                        <th className="tnum px-3 py-2 text-right font-medium">SOT</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Tkl</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Int</th>
                        <th className="tnum px-3 py-2 text-right font-medium">Fouls</th>
                        <th className="tnum px-3 py-2 text-right font-medium">YC</th>
                        <th className="tnum px-3 py-2 text-right font-medium">RC</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {rows.map((s) => (
                        <tr key={`${s.team_id}-${s.competition_code}-${s.season}`}>
                          <td className="px-4 py-2">
                            <Link
                              href={`/team/${s.team_id}`}
                              className="transition hover:text-accent"
                            >
                              {s.team}
                            </Link>
                          </td>
                          <td className="tnum px-3 py-2 text-right">{s.appearances}</td>
                          <td className="tnum px-3 py-2 text-right">{s.starts}</td>
                          <td className="tnum px-3 py-2 text-right">{s.minutes}</td>
                          <td className="tnum px-3 py-2 text-right font-medium">
                            {s.goals}
                          </td>
                          <td className="tnum px-3 py-2 text-right">{s.assists}</td>
                          <td className="tnum px-3 py-2 text-right">{num(s.shots)}</td>
                          <td className="tnum px-3 py-2 text-right">
                            {num(s.shots_on_target)}
                          </td>
                          <td className="tnum px-3 py-2 text-right">{num(s.tackles)}</td>
                          <td className="tnum px-3 py-2 text-right">
                            {num(s.interceptions)}
                          </td>
                          <td className="tnum px-3 py-2 text-right">{num(s.fouls)}</td>
                          <td className="tnum px-3 py-2 text-right">{s.yellows}</td>
                          <td className="tnum px-3 py-2 text-right">{s.reds}</td>
                        </tr>
                      ))}
                      {rows.map((s) =>
                        s.minutes > 0 ? (
                          <tr
                            key={`${s.team_id}-p90`}
                            className="text-muted"
                          >
                            <td className="px-4 py-2 text-xs">Per 90</td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              —
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              —
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {s.appearances
                                ? (s.minutes / s.appearances).toFixed(0)
                                : "—"}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.goals, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.assists, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.shots, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.shots_on_target, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.tackles, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.interceptions, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.fouls, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.yellows, s.minutes)}
                            </td>
                            <td className="tnum px-3 py-2 text-right text-xs">
                              {per90(s.reds, s.minutes)}
                            </td>
                          </tr>
                        ) : null
                      )}
                    </tbody>
                  </table>
                </div>
                <p className="border-t border-border px-4 py-2 text-xs text-muted">
                  {rows.some((s) => s.source === "appearance")
                    ? "Shots, tackles and interceptions come from the match sheet. Per 90 is the season total scaled to ninety minutes."
                    : rows.some((s) => s.source === "api")
                      ? "Season totals from the match provider, including recorded minutes. Per 90 is the season total scaled to ninety minutes."
                      : "Minutes are 90 per start; substitutes are not guessed. Shots, tackles and fouls are only stored where a richer source exists."}
                </p>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
