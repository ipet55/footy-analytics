import Link from "next/link";
import { Badge } from "@/components/Badge";
import { Flag } from "@/components/Flag";
import { supabase } from "@/lib/supabase";
import { COMPETITIONS, type Team } from "@/lib/types";

export const revalidate = 300;

const PAGE_SIZE = 120;

export default async function TeamsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; competition?: string }>;
}) {
  const { q, competition } = await searchParams;
  const query = (q ?? "").trim();

  let request = supabase
    .from("team")
    .select("*")
    .order("latest_start_year", { ascending: false })
    .order("matches", { ascending: false })
    .limit(PAGE_SIZE);

  if (query) {
    // Search the canonical name only. Matching on the alias table would find
    // more spellings but return the same club several times, which reads as
    // duplicates rather than as thoroughness.
    request = request.ilike("team", `%${query}%`);
  }
  if (competition && COMPETITIONS[competition]) {
    request = request.contains("competitions", [competition]);
  }

  const { data, error } = await request;
  if (error) {
    return (
      <div className="rounded-lg border border-edge-negative/40 bg-edge-negative/5 p-4 text-sm">
        Could not load teams: {error.message}
      </div>
    );
  }
  const teams = (data ?? []) as Team[];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Teams</h1>
        <p className="mt-1 text-sm text-muted">
          Season histories counted from matches played — how often a team went
          over each line, split home and away.
        </p>
      </div>

      {/* A plain GET form: search needs no client-side JavaScript, and the URL
          staying shareable is worth more than avoiding a page load. */}
      <form action="/teams" className="flex flex-wrap gap-2">
        <input
          type="search"
          name="q"
          defaultValue={query}
          placeholder="Search a club — Galatasaray, Arsenal, Porto…"
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-accent/50"
          aria-label="Search teams by name"
        />
        {competition && <input type="hidden" name="competition" value={competition} />}
        <button
          type="submit"
          className="rounded-lg border border-accent/50 bg-accent/10 px-4 py-2 text-sm text-accent transition hover:bg-accent/20"
        >
          Search
        </button>
      </form>

      <nav className="flex flex-wrap gap-2">
        <Chip
          active={!competition}
          href={query ? `/teams?q=${encodeURIComponent(query)}` : "/teams"}
          label="All competitions"
        />
        {Object.entries(COMPETITIONS).map(([code, name]) => (
          <Chip
            key={code}
            active={competition === code}
            href={`/teams?competition=${encodeURIComponent(code)}${
              query ? `&q=${encodeURIComponent(query)}` : ""
            }`}
            label={name}
            competition={code}
          />
        ))}
      </nav>

      {teams.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-6 text-sm text-muted">
          No club matches {query ? `“${query}”` : "that filter"}.
        </p>
      ) : (
        <>
          <p className="text-xs text-muted">
            {teams.length === PAGE_SIZE
              ? `First ${PAGE_SIZE} clubs — narrow the search to see more`
              : `${teams.length} ${teams.length === 1 ? "club" : "clubs"}`}
          </p>
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {teams.map((t) => (
              <li key={t.team_id}>
                <Link
                  href={`/team/${t.team_id}`}
                  className="block rounded-lg border border-border bg-surface px-4 py-3 transition hover:bg-surface-raised"
                >
                  <span className="flex items-center gap-2">
                    <Badge src={t.logo_url} name={t.team} size={28} />
                    <span className="block truncate text-sm font-medium">
                      {t.team}
                    </span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted">
                    {t.country ?? "Europe"} · {t.matches} matches ·{" "}
                    {t.competitions
                      .map((c) => COMPETITIONS[c] ?? c)
                      .slice(0, 2)
                      .join(", ")}
                    {t.competitions.length > 2
                      ? ` +${t.competitions.length - 2}`
                      : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Chip({
  active,
  href,
  label,
  competition,
}: {
  active: boolean;
  href: string;
  label: string;
  competition?: string;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
        active
          ? "border-accent/50 bg-accent/10 text-accent"
          : "border-border bg-surface text-muted hover:text-foreground"
      }`}
    >
      {competition && <Flag competition={competition} size={12} />}
      {label}
    </Link>
  );
}
