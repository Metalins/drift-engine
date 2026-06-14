/**
 * Shared layout for /docs and every /docs/** sub-route.
 *
 * Sprint UX-5.15.F — task #846. The /docs surface was a single 4000-word
 * page with a flat 14-pill TOC, which the Andrea audit
 * (docs/audits/ANDREA-DOCS-AUDIT-2026-05-19.md) identified as the root
 * cause of friction for non-technical visitors. This layout wraps the
 * new hub + sub-routes so every doc page gets:
 *
 *   • Breadcrumb (Docs / Section / Page) computed from pathname.
 *   • "← Back to docs" link.
 *   • Sidebar listing the four groups + their pages, so a visitor can
 *     navigate without bouncing back to the hub.
 *
 * Client component because we use usePathname() to derive crumbs.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

type NavLink = { href: string; label: string };
type NavGroup = { label: string; links: NavLink[] };

const NAV: NavGroup[] = [
  {
    // Hybrid ordering (UX-5.17 + Tanda B). The HTTP API / SDK is still
    // the primary connect path — the "Three ways to connect" section
    // and the /connect picker both mark it primary. But the zero-code
    // Public-bot watcher leads the list as a visible on-ramp for
    // non-developers, who would otherwise bounce off an API-first menu
    // (all four persona reviews flagged this). The developer-API page
    // is genuinely a how-to-connect page (basics + the SDK quickstart),
    // so it lives here, not under Reference.
    label: "Getting started",
    links: [
      { href: "/drift-engine/docs/getting-started", label: "What Drift Engine is" },
      // HIDE: not for Diana — Public-bot watcher is for Carlos. Page kept,
      // hidden from nav. { href: "/drift-engine/docs/getting-started/bot-watcher", label: "Public-bot watcher" },
      { href: "/drift-engine/docs/reference/developer-api", label: "HTTP API / SDK" },
      // HIDE: not for Diana — MCP setup not relevant. Page kept, hidden from
      // nav. { href: "/drift-engine/docs/getting-started/mcp-setup", label: "MCP setup" },
    ],
  },
  {
    label: "Concepts",
    links: [
      {
        href: "/drift-engine/docs/concepts/what-metalins-catches",
        label: "What Drift Engine catches",
      },
      { href: "/drift-engine/docs/concepts/tiers", label: "Identity tiers" },
      {
        href: "/drift-engine/docs/concepts/cryptographic-identity",
        label: "Cryptographic identity",
      },
      { href: "/drift-engine/docs/concepts/availability", label: "Availability" },
      {
        href: "/drift-engine/docs/concepts/what-leaves-your-infra",
        label: "What leaves your infra",
      },
      {
        href: "/drift-engine/docs/concepts/behavioral-baseline",
        label: "Behavior pattern",
      },
      { href: "/drift-engine/docs/concepts/drift-detection", label: "Drift signals" },
      {
        href: "/drift-engine/docs/concepts/integration-lifecycle",
        label: "Integration lifecycle",
      },
    ],
  },
  {
    label: "Use cases",
    links: [
      // HIDE: not for Diana — Personal AI is for Andrea. Page kept, hidden
      // from nav. { href: "/drift-engine/docs/use-cases/personal", label: "Personal AI" },
      { href: "/drift-engine/docs/use-cases/drift", label: "Drift detection" },
      { href: "/drift-engine/docs/use-cases/compliance", label: "Compliance & audit" },
    ],
  },
  {
    // Tanda B — the "prove your agent to a third party" story had no
    // home in the menu (all four persona reviews flagged it). This
    // group gathers it end to end: the threat model (what a link
    // proves), the verify-proof endpoint (how a relying party checks
    // it), and the agent-to-agent use case. The pages keep their
    // /reference and /use-cases URLs for stability — this is purely a
    // navigation grouping.
    label: "Prove your agent",
    links: [
      { href: "/drift-engine/docs/reference/threat-model", label: "Threat model" },
      {
        href: "/drift-engine/docs/reference/verify-proof",
        label: "Verify-proof endpoint",
      },
      { href: "/drift-engine/docs/use-cases/agent-to-agent", label: "Agent-to-agent" },
    ],
  },
  // HIDE: Reference group — Webhook payload is not for Diana (SDK-first).
  // Page kept at /docs/reference/webhooks, just not promoted in nav.
  // {
  //   label: "Reference",
  //   links: [
  //     { href: "/drift-engine/docs/reference/webhooks", label: "Webhook payload" },
  //   ],
  // },
];

const HUB_HREF = "/drift-engine/docs";

function labelForHref(href: string): string | null {
  for (const group of NAV) {
    for (const link of group.links) {
      if (link.href === href) return link.label;
    }
  }
  return null;
}

function groupForHref(href: string): NavGroup | null {
  for (const group of NAV) {
    for (const link of group.links) {
      if (link.href === href) return group;
    }
  }
  return null;
}

function Breadcrumb({ pathname }: { pathname: string }) {
  const isHub = pathname === HUB_HREF;
  const pageLabel = labelForHref(pathname);
  const group = groupForHref(pathname);

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground"
    >
      <Link href={HUB_HREF} className="hover:text-foreground hover:underline">
        Drift Engine docs
      </Link>
      {!isHub && group && (
        <>
          <span aria-hidden>/</span>
          <span>{group.label}</span>
        </>
      )}
      {!isHub && pageLabel && (
        <>
          <span aria-hidden>/</span>
          <span className="text-foreground">{pageLabel}</span>
        </>
      )}
    </nav>
  );
}

function Sidebar({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="Docs navigation" className="space-y-6 text-sm">
      {NAV.map((group) => (
        <div key={group.label}>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {group.label}
          </p>
          <ul className="mt-2 space-y-1">
            {group.links.map((link) => {
              const active = pathname === link.href;
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={
                      active
                        ? "block rounded-md bg-accent px-2 py-1 font-medium text-foreground"
                        : "block rounded-md px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                    }
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() ?? HUB_HREF;
  const isHub = pathname === HUB_HREF;
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-20 pt-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Breadcrumb pathname={pathname} />
        {!isHub && (
          <Link
            href={HUB_HREF}
            className="text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            ← Back to docs
          </Link>
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
        {/* Sidebar — sticky on lg+, collapsible on smaller screens. */}
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <button
            type="button"
            onClick={() => setSidebarOpen((s) => !s)}
            aria-expanded={sidebarOpen}
            className="mb-3 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
          >
            {sidebarOpen ? "Hide navigation" : "Show navigation"}
          </button>
          <div className={sidebarOpen ? "block" : "hidden lg:block"}>
            <Sidebar pathname={pathname} />
          </div>
        </aside>

        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
