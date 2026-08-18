"use client";

import { useState } from "react";

/** A club badge. Falls back to nothing rather than a broken square: a missing
 *  badge next to a name is fine, a grey box is not.
 */
export function Badge({
  src,
  name,
  size = 24,
}: {
  src: string | null;
  name: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  const dim = `${size}px`;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      title={name}
      onError={() => setFailed(true)}
      className="inline-block shrink-0 object-contain"
      style={{ width: dim, height: dim }}
    />
  );
}
