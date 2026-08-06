import Link from "next/link";
import { formatDateShort } from "@/lib/format";
import { supabase } from "@/lib/supabase";
import { COMPETITIONS, type Fixture } from "@/lib/types";

export const revalidate = 300;

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ competition?: string }>;
}) {
  const { competition } = await searchParams;

  let query = supabase
    .from("fixture")
    .select("*")
    .eq("has_predictions", true)
    .order("kickoff_date", { ascending: false })
    .limit(300);

  if (competition && COMPETITIONS[competition]) {
    query = query.eq("competition_code", competition);
  }

  const { data, error } = await query;

  if (error) {
    return (
      <div className="rounded-lg border border-edge-negative/40 bg-edge-negative/5 p-4 text-sm">
        Could not load fixtures: {error.message}
      </div>
    );
  }

  const fixtures = (data ?? []) as Fixture[];
  const byDate = new Map<string, Fixture[]>();
  for (const fixture of fixtures) {
    const list = byDate.get(fixture.kickoff_date) ?? [];
    list.push(fixture);
    byDate.set(fixture.kickoff_date, list);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fixtures</h1>
        <p className="mt-1 text-sm text-muted">
          {fixtures.length} matches with stored probabilities. Every one was
          predicted before kickoff by a model fitted only on earlier matches.
        </p>
      </div>

      <nav className="flex flex-wrap gap-2">
        <FilterChip active={!competition} href="/" label="All leagues" />
        {Object.entries(COMPETITIONS).map(([code, name]) => (
          <FilterChip
            key={code}
            active={competition === code}
            href={`/?competition=${encodeURIComponent(code)}`}
            label={name}
          />
        ))}
      </nav>

      {byDate.size === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-6 text-sm text-muted">
          No fixtures have stored predictions yet. Run{" "}
          <code className="text-accent">footy predict</code> to generate some.
        </p>
      ) : (
        <div className="space-y-8">
          {[...byDate.entries()].map(([date, matches]) => (
            <section key={date}>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-widest text-muted">
                {formatDateShort(date)}
              </h2>
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
                {matches.map((m) => (
                  <li key={m.match_id}>
                    <Link
                      href={`/match/${m.match_id}`}
                      className="grid grid-cols-[auto_1fr_auto] items-center gap-4 px-4 py-3 transition hover:bg-surface-raised"
                    >
                      <span className="w-24 shrink-0 text-xs text-muted">
                        {COMPETITIONS[m.competition_code] ?? m.competition_code}
                      </span>
                      <span className="min-w-0 truncate text-sm">
                        <span className="font-medium">{m.home_team}</span>
                        <span className="mx-2 text-muted">v</span>
                        <span className="font-medium">{m.away_team}</span>
                      </span>
                      <span className="tnum text-sm text-muted">
                        {m.home_goals_ft !== null && m.away_goals_ft !== null
                          ? `${m.home_goals_ft}–${m.away_goals_ft}`
                          : "—"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  href,
  label,
}: {
  active: boolean;
  href: string;
  label: string;
}) {
  return (
    <Link
      href={href}
      className={`rounded-full border px-3 py-1 text-xs transition ${
        active
          ? "border-accent/50 bg-accent/10 text-accent"
          : "border-border bg-surface text-muted hover:text-foreground"
      }`}
    >
      {label}
    </Link>
  );
}
