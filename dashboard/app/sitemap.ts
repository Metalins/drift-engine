/**
 * Dynamic sitemap.xml — Sprint 4.10, expanded in Sprint UX-5.15.F (#846).
 *
 * Lists every public, indexable page. When ALLOW_INDEX=false, returns
 * an empty sitemap so crawlers see nothing. When true, lists landing,
 * the docs hub, every docs sub-route (concepts / use-cases / reference),
 * and login.
 *
 * Private pages (/dashboard, /agents, /api, /auth) are never listed.
 */
import type { MetadataRoute } from "next";

// gh-98 (2026-06-15): metalins.com is the canonical domain; the sitemap
// lists canonical URLs so crawlers index metalins.com, not the 301'd .ai.
const BASE_URL = "https://metalins.com";

const DOCS_SUBROUTES = [
  "/drift-engine/docs/getting-started",
  "/drift-engine/docs/reference/developer-api",
  "/drift-engine/docs/concepts/what-metalins-catches",
  "/drift-engine/docs/concepts/tiers",
  "/drift-engine/docs/concepts/cryptographic-identity",
  "/drift-engine/docs/concepts/availability",
  "/drift-engine/docs/concepts/what-leaves-your-infra",
  "/drift-engine/docs/concepts/behavioral-baseline",
  "/drift-engine/docs/concepts/drift-detection",
  "/drift-engine/docs/concepts/integration-lifecycle",
  // HIDE: not for Diana — Personal AI is for Andrea. Page kept, removed from
  // sitemap so it is not promoted to crawlers.
  "/drift-engine/docs/use-cases/drift",
  "/drift-engine/docs/use-cases/compliance",
  "/drift-engine/docs/use-cases/agent-to-agent",
  "/drift-engine/docs/reference/verify-proof",
  "/drift-engine/docs/reference/threat-model",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const allow = process.env.NEXT_PUBLIC_ALLOW_INDEX === "true";
  if (!allow) return [];

  const now = new Date();
  const base: MetadataRoute.Sitemap = [
    {
      url: `${BASE_URL}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/drift-engine/docs`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      // gh-101 (2026-06-15): /products is a real, indexable route now —
      // the lab wants its products discoverable.
      url: `${BASE_URL}/products`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/writing`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/terms`,
      lastModified: now,
      changeFrequency: "yearly",
      priority: 0.2,
    },
    {
      url: `${BASE_URL}/privacy`,
      lastModified: now,
      changeFrequency: "yearly",
      priority: 0.2,
    },
  ];
  const sub: MetadataRoute.Sitemap = DOCS_SUBROUTES.map((p) => ({
    url: `${BASE_URL}${p}`,
    lastModified: now,
    changeFrequency: "weekly" as const,
    priority: 0.7,
  }));
  return [...base, ...sub];
}
