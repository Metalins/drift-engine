/**
 * Next.js config — Metalins dashboard.
 *
 * Anti-indexación 3-layers (Sprint 3a.5 + D-PROD.14 + D-PROD.16):
 *   1. `X-Robots-Tag: noindex, nofollow` header (this file).
 *   2. `public/robots.txt` Disallow: /
 *   3. `<meta name="robots" content="noindex, nofollow">` in layout.
 *
 * Set `NEXT_PUBLIC_ALLOW_INDEX=true` to disable all three at once
 * (day-of-launch flip — see SPRINT-3-PLAN.md "Day-of-launch checklist").
 */
const ALLOW_INDEX = process.env.NEXT_PUBLIC_ALLOW_INDEX === "true";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Self-hosting (gh-119): emit a standalone server bundle so the Docker image
  // can run `node server.js` with a minimal copy of node_modules.
  output: "standalone",
  // Board #50 — /for-personal-assistant is retired (Diana-only home). Send a
  // hard 301 to / so the old persona URL stops serving a stale H1 and any
  // residual link/bookmark lands on the live landing. `statusCode: 301`
  // (not `permanent: true`, which Next emits as 308) is required so the
  // redirect reads as a literal 301 to curl/crawlers.
  async redirects() {
    return [
      {
        source: "/for-personal-assistant",
        destination: "/",
        statusCode: 301,
      },
      // gh-107 (2026-06-15): docs moved to a per-product path —
      // /docs → /drift-engine/docs. Metalins is a lab with multiple
      // products; each owns its docs. A literal 301 (not Next's 308
      // `permanent: true`) preserves existing links/bookmarks and SEO
      // for crawlers. Two rules: the bare hub and every sub-route.
      {
        source: "/docs",
        destination: "/drift-engine/docs",
        statusCode: 301,
      },
      {
        source: "/docs/:path*",
        destination: "/drift-engine/docs/:path*",
        statusCode: 301,
      },
    ];
  },
  async headers() {
    if (ALLOW_INDEX) return [];
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
    ];
  },
};

export default nextConfig;
