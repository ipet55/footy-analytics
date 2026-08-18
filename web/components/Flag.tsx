"use client";

import { useState } from "react";
import { flagUrl } from "@/lib/flags";

export function Flag({
  competition,
  size = 14,
}: {
  competition: string;
  size?: number;
}) {
  const src = flagUrl(competition, size <= 16 ? 20 : 40);
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={size}
      height={Math.round(size * 0.75)}
      onError={() => setFailed(true)}
      className="inline-block shrink-0 rounded-[2px] object-cover"
    />
  );
}
