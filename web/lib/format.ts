/**
 * Deterministic date formatting.
 *
 * `toLocaleDateString` is resolved by whichever ICU build is running, so the
 * server and the browser can disagree on abbreviations or separators and React
 * reports a hydration mismatch. These dates are fixed English match dates with
 * no user locale to respect, so formatting them by hand removes the whole class
 * of problem rather than papering over it with suppressHydrationWarning.
 */

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const DAYS_LONG = [
  "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
] as const;
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const;

/** Parsed as UTC so the calendar date never shifts with the viewer's timezone. */
function parse(isoDate: string) {
  return new Date(`${isoDate}T00:00:00Z`);
}

export function formatDateShort(isoDate: string) {
  const d = parse(isoDate);
  return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function formatDateLong(isoDate: string) {
  const d = parse(isoDate);
  return `${DAYS_LONG[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS_LONG[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
