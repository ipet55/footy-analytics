import Link from "next/link";
import { Photo } from "@/components/Photo";

export function PlayerLink({
  id,
  name,
  photo,
  strike = false,
  muted = false,
  size = 22,
}: {
  id: number | null;
  name: string;
  photo: string | null;
  strike?: boolean;
  muted?: boolean;
  size?: number;
}) {
  const label = (
    <span
      className={`min-w-0 truncate ${
        strike
          ? "text-edge-negative line-through decoration-1"
          : muted
            ? "text-muted"
            : ""
      }`}
    >
      {name}
    </span>
  );

  return (
    <span className="flex min-w-0 items-center gap-2">
      <Photo src={photo} name={name} size={size} />
      {id ? (
        <Link
          href={`/player/${id}`}
          className="min-w-0 truncate transition hover:text-accent"
        >
          {label}
        </Link>
      ) : (
        label
      )}
    </span>
  );
}
