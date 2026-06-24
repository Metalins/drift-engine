/**
 * Legacy-domain redirect logic — gh-98 (2026-06-15).
 *
 * metalins.com is now the canonical front door of the lab. The old
 * apex domain metalins.ai (and its www. variant) still resolve to the
 * same Cloudflare Worker, so any request that arrives there must be
 * sent on to the same path on metalins.com with a permanent 301 so
 * crawlers consolidate ranking signals onto the new domain.
 *
 * IMPORTANT: this is the *site* domain only. api.metalins.ai is a
 * different host (José's private API) and is never matched here — the
 * dashboard Worker doesn't serve api.metalins.ai, so its requests
 * never reach this code, and even if a header said otherwise we match
 * only the bare site hosts below.
 *
 * Kept as a pure function (no next/server import) so it is unit-testable
 * under Node's test runner without pulling the Next runtime.
 */

/** Site hosts that should be permanently redirected to metalins.com. */
const LEGACY_SITE_HOSTS = new Set(["metalins.ai", "www.metalins.ai"]);

/**
 * Given the incoming Host header, decide whether the request must be
 * redirected to metalins.com. Returns the absolute destination URL
 * (path + query preserved) or null when no redirect is needed.
 *
 * @param host    the request Host header (may include a :port, which is
 *                stripped before matching — prod is always :443).
 * @param pathnameAndQuery  the path plus any query string, e.g. "/docs?a=1".
 */
export function legacyDomainRedirect(
  host: string | null | undefined,
  pathnameAndQuery: string,
): string | null {
  if (!host) return null;
  // Normalize: lowercase + drop any port suffix (host:443 → host).
  const bareHost = host.toLowerCase().split(":")[0];
  if (!LEGACY_SITE_HOSTS.has(bareHost)) return null;
  const path = pathnameAndQuery.startsWith("/")
    ? pathnameAndQuery
    : `/${pathnameAndQuery}`;
  return `https://metalins.com${path}`;
}
