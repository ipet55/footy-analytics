/** League country → a flagcdn.com region code.
 *
 * England is `gb-eng` rather than `gb`, because the Premier League is not a
 * United Kingdom competition and the St George's Cross is what a reader
 * expects next to it. UEFA competitions use the EU flag: there is no honest
 * national flag for a continent-wide cup.
 */
export const LEAGUE_FLAG: Record<string, string> = {
  "ENG-PL": "gb-eng",
  "ESP-LL": "es",
  "GER-BL": "de",
  "ITA-SA": "it",
  "FRA-L1": "fr",
  "NED-ED": "nl",
  "POR-PL": "pt",
  "TUR-SL": "tr",
  "BEL-PL": "be",
  "BUL-1L": "bg",
  "CZE-1L": "cz",
  "NOR-EL": "no",
  "INT-UCL": "eu",
  "INT-UEL": "eu",
};

export function flagUrl(competitionCode: string, width = 40): string | null {
  const code = LEAGUE_FLAG[competitionCode];
  if (!code) return null;
  return `https://flagcdn.com/w${width}/${code}.png`;
}
