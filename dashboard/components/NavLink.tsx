/**
 * NavLink — top-nav item with active-state highlight that survives
 * client-side navigation.
 *
 * Sprint UX-5.15.Z follow-up (2026-05-19). The previous version was a
 * server-rendered helper that read the pathname from a `x-pathname`
 * header set by middleware. That worked for the initial page load but
 * broke after a Link click: the root layout is cached across
 * App-Router soft navigations, so the layout's `headers()` snapshot
 * stayed stuck on the route the user first landed on. Result: the
 * "Dashboard" link kept rendering as active even after navigating to
 * /settings or /docs.
 *
 * We move the active-state logic into a tiny Client Component that
 * calls `usePathname()`. That hook updates on every navigation, so
 * the highlight follows the user correctly. The rest of TopNav
 * (auth check, layout shell) stays server-rendered.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavLinkProps {
  href: string;
  children: React.ReactNode;
  icon: React.ReactNode;
  /**
   * Additional path prefixes that should also light this link up. We
   * use this to make "Dashboard" active across `/agents/...` (the
   * dashboard IS the agents list) and "Settings" active under `/keys`
   * (Keys was promoted into the Settings page).
   */
  activeRoots?: string[];
}

export function NavLink({ href, children, icon, activeRoots }: NavLinkProps) {
  const pathname = usePathname() ?? "";
  const roots = [href, ...(activeRoots ?? [])];
  const isActive = roots.some(
    (r) => pathname === r || pathname.startsWith(r + "/"),
  );
  return (
    <Link
      href={href}
      className={
        isActive
          ? "inline-flex items-center gap-1.5 rounded-md bg-foreground/[0.06] px-3 py-1.5 text-sm font-medium text-foreground"
          : "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      }
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}
