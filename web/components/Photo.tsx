"use client";

import { useState } from "react";

function initials(name: string) {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** A player's photograph, or the two-letter fallback when the feed has none.
 *
 * Client-side because a 404 from the CDN is common — the provider keeps a
 * URL for players it has never photographed — and a broken image is worse
 * than initials.
 */
export function Photo({
  src,
  name,
  size = 28,
}: {
  src: string | null;
  name: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const dim = `${size}px`;

  if (!src || failed) {
    return (
      <span
        className="inline-flex shrink-0 items-center justify-center rounded-full bg-surface-raised text-[10px] font-medium text-muted"
        style={{ width: dim, height: dim }}
        aria-hidden
      >
        {initials(name)}
      </span>
    );
  }

  return (
    // External CDN. next/image would need a domain allow-list for one host
    // that already serves the squad photos we store.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      onError={() => setFailed(true)}
      className="inline-block shrink-0 rounded-full object-cover"
      style={{ width: dim, height: dim }}
    />
  );
}
