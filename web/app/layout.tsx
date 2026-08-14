import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Footy Analytics",
  description:
    "Match probabilities from a model trained on twelve seasons, shown next to the closing market price.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        <header className="border-b border-border bg-surface/60 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-lg font-semibold tracking-tight">
                Footy Analytics
              </span>
              <span className="hidden text-xs text-muted sm:inline">
                model vs market
              </span>
            </Link>
            <nav className="flex items-center gap-5 text-sm">
              <Link
                href="/"
                className="text-muted transition hover:text-foreground"
              >
                Fixtures
              </Link>
              <Link
                href="/teams"
                className="text-muted transition hover:text-foreground"
              >
                Teams
              </Link>
              <Link
                href="/accuracy"
                className="text-muted transition hover:text-foreground"
              >
                Track record
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
        <footer className="mx-auto max-w-6xl px-5 pb-10 pt-4 text-xs leading-relaxed text-muted">
          Probabilities are recalibrated on the model&apos;s own past predictions and
          are only shown for markets validated walk-forward across five leagues.
          Markets that did not earn publication are not served by the API at all.
        </footer>
      </body>
    </html>
  );
}
