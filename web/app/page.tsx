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

  // Two queries rather than one, because the two halves of the page want
  // opposite orderings: the next match to be played should come first, and the
  // most recently played one should lead the results below it. A match counts as
  // upcoming when it has no score, which needs no reference to the clock.
  const scoped = () => {
    const q = supabase.from("fixture").select("*").eq("has_predictions", true);
    return competition && COMPETITIONS[competition]
      ? q.eq("competition_code", competition)
      : q;
  };

  const [upcoming, played, servedRes] = await Promise.all([
    scoped()
      .is("home_goals_ft", null)
      .order("kickoff_date", { ascending: true })
      .limit(200),
    scoped()
      .not("home_goals_ft", "is", null)
      .order("kickoff_date", { ascending: false })
      .limit(200),
    // Which competitions publish anything. Eight are loaded and measured but
    // publish nothing yet, so a chip list taken from the label map would offer
    // five filters that lead to an empty page.
    supabase.from("market").select("competition_code"),
  ]);

  const error = upcoming.error ?? played.error;
  if (error) {
    return (
      <div className="rounded-lg border border-edge-negative/40 bg-edge-negative/5 p-4 text-sm">
        Could not load fixtures: {error.message}
      </div>
    );
  }

  const fixtures = (upcoming.data ?? []) as Fixture[];
  const results = (played.data ?? []) as Fixture[];

  // The match-result probabilities for the upcoming fixtures. Without them an
  // upcoming fixture ends in a dash — the empty score column — which reads as
  // "no prediction" when there are fifty of them one click away. A played match
  // shows its score instead and needs none of this.
  //
  // Requested in batches because PostgREST caps a response at 1000 rows and says
  // nothing when it truncates: asking about 400 matches returned three
  // probabilities each for the first 333 and silence for the rest, so most of the
  // page read "not priced" while the database held every number. Three rows per
  // match means 300 matches is the largest batch that cannot be cut short.
  const outcome = new Map<number, Record<string, number>>();
  const BATCH = 300;
  for (let i = 0; i < fixtures.length; i += BATCH) {
    const ids = fixtures.slice(i, i + BATCH).map((f) => f.match_id);
    const { data } = await supabase
      .from("prediction")
      .select("match_id,selection,probability")
      .eq("market_code", "goals_1x2")
      .in("match_id", ids);
    for (const row of (data ?? []) as Array<{
      match_id: number;
      selection: string;
      probability: number;
    }>) {
      const entry = outcome.get(row.match_id) ?? {};
      entry[row.selection] = Number(row.probability);
      outcome.set(row.match_id, entry);
    }
  }

  const served = [
    ...new Set(
      ((servedRes.data ?? []) as Array<{ competition_code: string }>).map(
        (m) => m.competition_code
      )
    ),
  ].sort(
    (a, b) =>
      Object.keys(COMPETITIONS).indexOf(a) - Object.keys(COMPETITIONS).indexOf(b)
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fixtures</h1>
        <p className="mt-1 text-sm text-muted">
          {fixtures.length} upcoming{" "}
          {fixtures.length === 1 ? "match" : "matches"} and {results.length}{" "}
          already played, all with stored probabilities. Every one was predicted
          before kickoff by a model fitted only on earlier matches.
        </p>
      </div>

      <nav className="flex flex-wrap gap-2">
        <FilterChip active={!competition} href="/" label="All leagues" />
        {served.map((code) => (
          <FilterChip
            key={code}
            active={competition === code}
            href={`/?competition=${encodeURIComponent(code)}`}
            label={COMPETITIONS[code] ?? code}
          />
        ))}
      </nav>

      {fixtures.length === 0 && results.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-6 text-sm text-muted">
          No fixtures have stored predictions yet. Run{" "}
          <code className="text-accent">footy predict</code> to generate some.
        </p>
      ) : (
        <div className="space-y-10">
          <FixtureGroups
            heading="Upcoming"
            fixtures={fixtures}
            outcome={outcome}
            empty="No upcoming fixtures have predictions yet."
          />
          <FixtureGroups heading="Results" fixtures={results} outcome={outcome} />
        </div>
      )}
    </div>
  );
}

function FixtureGroups({
  heading,
  fixtures,
  outcome,
  empty,
}: {
  heading: string;
  fixtures: Fixture[];
  outcome: Map<number, Record<string, number>>;
  empty?: string;
}) {
  if (fixtures.length === 0) {
    return empty ? (
      <section>
        <SectionHeading>{heading}</SectionHeading>
        <p className="rounded-lg border border-border bg-surface p-6 text-sm text-muted">
          {empty}
        </p>
      </section>
    ) : null;
  }

  const byDate = new Map<string, Fixture[]>();
  for (const fixture of fixtures) {
    const list = byDate.get(fixture.kickoff_date) ?? [];
    list.push(fixture);
    byDate.set(fixture.kickoff_date, list);
  }

  return (
    <section>
      <SectionHeading>{heading}</SectionHeading>
      <div className="space-y-8">
        {[...byDate.entries()].map(([date, matches]) => (
          <section key={date}>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-widest text-muted">
              {formatDateShort(date)}
            </h3>
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
                    {m.home_goals_ft !== null && m.away_goals_ft !== null ? (
                      <span className="tnum text-sm">
                        {m.home_goals_ft}–{m.away_goals_ft}
                      </span>
                    ) : (
                      <Outcome probabilities={outcome.get(m.match_id)} />
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </section>
  );
}

/** Home, draw and away as the model sees them, in the column a played match
 *  uses for its score. Labelled so three bare numbers cannot be mistaken for
 *  one, and the largest is emphasised because that is what the eye is after. */
function Outcome({
  probabilities,
}: {
  probabilities?: Record<string, number>;
}) {
  if (!probabilities) {
    return <span className="text-xs text-muted">not priced</span>;
  }
  const cells: Array<[string, number | undefined]> = [
    ["1", probabilities.home],
    ["X", probabilities.draw],
    ["2", probabilities.away],
  ];
  const best = Math.max(...cells.map(([, v]) => v ?? 0));
  return (
    <span className="flex shrink-0 items-center gap-2">
      {cells.map(([label, value]) => (
        <span key={label} className="flex w-12 flex-col items-end leading-tight">
          <span className="text-[10px] uppercase tracking-widest text-muted">
            {label}
          </span>
          <span
            className={`tnum text-sm ${
              value === best ? "font-medium text-foreground" : "text-muted"
            }`}
          >
            {value === undefined ? "—" : `${Math.round(value * 100)}%`}
          </span>
        </span>
      ))}
    </span>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-sm font-semibold tracking-tight">{children}</h2>
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
