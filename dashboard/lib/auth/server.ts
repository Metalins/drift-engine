/**
 * Server-side auth helpers for the self-hosted dashboard.
 *
 * Self-hosting pivot (gh-119): the dashboard no longer delegates login to
 * Supabase. The Drift Engine server (FastAPI) owns auth — `POST /auth/login`
 * mints a short-lived HS256 session JWT. The dashboard stores that JWT in an
 * httpOnly cookie (`ml_session`) and forwards it to the server as
 * `Authorization: Bearer <jwt>` on every BFF call.
 *
 * This module is server-only (it imports next/headers) and exposes the same
 * surface the rest of the app used to import from `@/lib/supabase/server`:
 *   - getAccessToken(): the raw JWT from the cookie, or null.
 *   - getCurrentUser(): { id, email } resolved via GET /internal/v1/me, or null.
 *
 * Keeping the function names identical means lib/api.ts, the layout and the
 * settings pages didn't need their call sites rewritten — only the import path.
 */
import { cookies } from "next/headers";

/** httpOnly cookie that holds the server-minted session JWT. */
export const SESSION_COOKIE = "ml_session";

/**
 * Base URL of the Drift Engine API server, as seen from inside the dashboard
 * container. In docker-compose this is the `server` service name. We read a
 * server-only env var (NOT NEXT_PUBLIC_*) because every consumer of this URL
 * runs server-side: the BFF fetches, the login route handler and getCurrentUser.
 */
export function serverApiUrl(): string {
  return (
    process.env.DRIFT_ENGINE_API_URL ||
    process.env.NEXT_PUBLIC_METALINS_API_URL ||
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

/**
 * Returns the current session's access token (JWT) or null if not logged in.
 * Used by lib/api.ts to forward the JWT to the Drift Engine server.
 */
export async function getAccessToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE)?.value ?? null;
}

/**
 * Returns the current authenticated user (email + id) or null.
 *
 * We don't verify the JWT signature locally — we ask the server who the
 * token belongs to via GET /internal/v1/me. That keeps the secret entirely
 * server-side and means a revoked/expired token is rejected by the source of
 * truth rather than by a stale local check.
 */
export async function getCurrentUser(): Promise<
  { id: string; email: string | null } | null
> {
  const token = await getAccessToken();
  if (!token) return null;

  try {
    const res = await fetch(`${serverApiUrl()}/internal/v1/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as {
      customer_id?: string;
      email?: string | null;
    };
    if (!body.customer_id) return null;
    return { id: body.customer_id, email: body.email ?? null };
  } catch {
    // Server unreachable — treat as logged-out rather than crashing the render.
    return null;
  }
}
