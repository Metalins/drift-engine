/**
 * Dynamic robots.txt — anti-indexation defense (D-PROD.14 + D-PROD.16).
 *
 * Sprint 3c.4 — when ALLOW_INDEX=true, only public routes are crawlable;
 * the dashboard and auth flow stay disallowed forever. Before alpha launch
 * (ALLOW_INDEX=false), nothing is crawlable.
 */
import type { MetadataRoute } from "next";

// gh-98 (2026-06-15): canonical domain is metalins.com. The robots.txt
// Sitemap directive must point at the canonical host so crawlers fetch
// the sitemap from metalins.com (the .ai host 301s here anyway).
const SITEMAP_URL = "https://metalins.com/sitemap.xml";

export default function robots(): MetadataRoute.Robots {
  const allow = process.env.NEXT_PUBLIC_ALLOW_INDEX === "true";
  if (allow) {
    return {
      rules: [
        {
          userAgent: "*",
          allow: "/",
          disallow: ["/dashboard/", "/agents/", "/login", "/auth/", "/api/"],
        },
      ],
      sitemap: SITEMAP_URL,
    };
  }
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
  };
}
