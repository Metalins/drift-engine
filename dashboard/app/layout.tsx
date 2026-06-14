/**
 * Root layout.
 *
 * Adapts based on auth state:
 *   • Logged-out visitors see the public product nav (Drift Engine logo +
 *     Docs + a GitHub link — see PublicNav). gh-121 (2026-06-24) stripped
 *     the old lab links (Research / Products / Writing) since this is the
 *     self-hosted product, not the metalins.com lab site.
 *   • Logged-in users see the account header (email + signout).
 *
 * Anti-indexation:
 *   • Site-wide default in `metadata.robots` is noindex when ALLOW_INDEX=false.
 *   • Per-page metadata can override (e.g. /dashboard always sets noindex).
 *   • robots.txt + next.config.mjs X-Robots-Tag still gate the global flag.
 */
import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { headers } from "next/headers";
import { BookOpen, LayoutGrid, LogOut, Settings as SettingsIcon } from "lucide-react";
import "./globals.css";
import { getCurrentUser } from "@/lib/auth/server";
import { NavLink } from "@/components/NavLink";
import { PublicNav } from "@/components/PublicNav";
import { Footer } from "@/components/Footer";

/**
 * Routes that get a stripped-down public layout (no internal nav, no
 * user menu). The visitor to these URLs is a stranger validating a
 * bot/agent — showing them "Dashboard" / "Sign out" is confusing and
 * leaks that the page lives inside our product. Sprint UX-5.7b (#635).
 */
const PUBLIC_LAYOUT_PREFIXES = ["/verify/", "/v/", "/not-me"];

function isPublicLayout(pathname: string): boolean {
  return PUBLIC_LAYOUT_PREFIXES.some((p) => pathname.startsWith(p));
}

const ALLOW_INDEX = process.env.NEXT_PUBLIC_ALLOW_INDEX === "true";

export const metadata: Metadata = {
  // gh-98 (2026-06-15): metalins.com is the canonical domain. metadataBase
  // anchors every relative OG/Twitter asset (e.g. /og-image.png) and the
  // canonical URL to metalins.com; metalins.ai 301s here via middleware.
  metadataBase: new URL("https://metalins.com"),
  // gh-121 (2026-06-24): this dashboard ships inside the public, self-hosted
  // Drift Engine repo. The default title/description identify the product —
  // not the Metalins research lab — so a self-hoster's tab and any link
  // preview read "Drift Engine", which is what they actually run.
  title: {
    default: "Drift Engine",
    template: "%s",
  },
  description:
    "Drift Engine — open-source behavioral fingerprinting for AI agents.",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
  robots: ALLOW_INDEX
    ? { index: true, follow: true }
    : { index: false, follow: false, nocache: true },
  openGraph: {
    title: "Drift Engine",
    description:
      "Open-source behavioral fingerprinting for AI agents.",
    siteName: "Drift Engine",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Drift Engine",
    description:
      "Open-source behavioral fingerprinting for AI agents.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

/**
 * UserEmail — informational pill on the right side of the nav.
 *
 * Sprint UX-5.15.Z: the prior nav rendered the raw email next to a
 * generic "Sign out" button which competed visually with the nav
 * links. We separate identity from the sign-out action: the email
 * reads as "you are signed in as X" (informational only) and Sign
 * Out becomes a small icon button with a tooltip — less prominent
 * because it's a rare action. Jose explicitly didn't want an avatar
 * circle, so we keep it pure text.
 */
function UserEmail({ email }: { email: string }) {
  return (
    <span className="hidden max-w-[180px] truncate text-xs text-muted-foreground sm:inline">
      {email}
    </span>
  );
}

/**
 * TopNav — adaptive header.
 *
 * Server Component. Reads the user from the Supabase session cookies
 * and the current pathname from the `x-pathname` header (set by
 * middleware). Shape differs based on whether someone is signed in.
 *
 * Sprint UX-5.15.Z reorganization (per Jose's request):
 *   • Dashboard first — it's the primary work surface.
 *   • Settings second — account-level config, including the API
 *     keys section (Keys page no longer has its own top-level
 *     entry; /settings now surfaces a link/section that goes to
 *     /keys, keeping the existing route working without cluttering
 *     the navbar with 4 top-level items).
 *   • Docs last — reference material, used less than Dashboard.
 *   • User identity (chip) + Sign Out grouped at the right edge,
 *     separated by a divider so the chip reads as "you are signed
 *     in as X" rather than another nav item.
 */
async function TopNav() {
  const user = await getCurrentUser();
  return (
    <header className="relative border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="" className="h-7 w-7" />
          <span className="text-base font-semibold tracking-tight">
            Drift Engine
          </span>
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          {user ? (
            <>
              <NavLink
                href="/dashboard"
                icon={<LayoutGrid size={14} aria-hidden />}
                // Highlight Dashboard while the user is inside any
                // /agents/* route — the dashboard IS the agents
                // browser, the detail/settings pages live under it.
                activeRoots={["/agents"]}
              >
                Dashboard
              </NavLink>
              <NavLink
                href="/settings"
                icon={<SettingsIcon size={14} aria-hidden />}
                // /keys was promoted into the Settings page (see the
                // ApiKeysSection card there); keep it lighting up the
                // Settings tab so the active state stays honest.
                activeRoots={["/keys"]}
              >
                Settings
              </NavLink>
              <NavLink
                href="/drift-engine/docs"
                icon={<BookOpen size={14} aria-hidden />}
              >
                Docs
              </NavLink>
              {/* UX-5.15.Z follow-up (mobile fix): the previous wrapper
                  was `hidden sm:flex`, which hid the entire user cluster
                  — email AND the sign-out button — on small screens.
                  The signout button MUST stay reachable on mobile, so
                  we make the outer cluster always-flex and only the
                  email pill (which would crowd a 320px viewport) is
                  responsive-hidden inside UserEmail. */}
              <div className="ml-2 flex items-center gap-2 border-l pl-2 sm:ml-3 sm:gap-3 sm:pl-3">
                <UserEmail email={user.email ?? user.id} />
                <form action="/auth/signout" method="POST">
                  <button
                    type="submit"
                    title="Sign out"
                    aria-label="Sign out"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <LogOut size={14} />
                  </button>
                </form>
              </div>
            </>
          ) : (
            // gh-113/114/116 (2026-06-15): the logged-out research-lab nav
            // moved into the PublicNav client component, which adds a
            // responsive hamburger collapse below 768px, a GitHub-org link,
            // and a faint admin sign-in entry. See PublicNav.tsx.
            <PublicNav />
          )}
        </nav>
      </div>
    </header>
  );
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Sprint UX-5.7b (#635) — read the request pathname (set in
  // middleware as `x-pathname`) and skip the internal nav for public
  // verify routes. Visitors landing on `/v/<slug>` or
  // `/verify/<id>` from Carlos's Telegram bio should NOT see
  // "Dashboard / Sign out" in the header.
  const hdrs = await headers();
  const pathname = hdrs.get("x-pathname") ?? "";
  const isPublic = isPublicLayout(pathname);

  return (
    <html lang="en" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col bg-background text-foreground antialiased">
        {isPublic ? <PublicTopBar /> : <TopNav />}
        <div className="container mx-auto max-w-6xl flex-1 px-4 py-6">
          {children}
        </div>
        <Footer />
      </body>
    </html>
  );
}

/**
 * PublicTopBar — minimal header used by /verify/* and /v/* only.
 *
 * No nav links, no user menu. Just the brand mark + a single CTA to the
 * product docs. A stranger validating an agent lands here either knowing
 * what Drift Engine is or not — the docs link lets them find out.
 * gh-121 (2026-06-24): rebranded from the Metalins lab to the Drift Engine
 * product, and the CTA now points at the docs instead of the lab landing.
 */
function PublicTopBar() {
  return (
    <header className="border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="" className="h-7 w-7" />
          <span className="text-base font-semibold tracking-tight">
            Drift Engine
          </span>
        </Link>
        <Link
          href="/drift-engine/docs"
          className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          What is Drift Engine? →
        </Link>
      </div>
    </header>
  );
}
