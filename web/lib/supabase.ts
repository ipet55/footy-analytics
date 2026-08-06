import { createClient } from "@supabase/supabase-js";

/**
 * The publishable key is safe in the browser only because of what it can reach:
 * the `anon` role has select on nine views in `public` and no access at all to
 * `core`, `ml`, `features` or `raw`. The views are the access control, not the
 * key. See sql/migrations/20260806203014_0012_public_views.sql.
 */
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!url || !key) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY must be set. " +
      "Copy .env.example to .env.local.",
  );
}

export const supabase = createClient(url, key, {
  auth: { persistSession: false },
});
