/**
 * Next.js middleware — runs before every matched request.
 *
 * Only the private app surface is gated. Landing (`/`), docs, the login page
 * and static files are public. Anything under /dashboard, /agents, /settings
 * (and their BFF /api proxies) requires a session.
 *
 * Self-hosting pivot (gh-119): the session is the httpOnly `ml_session` cookie
 * holding the Drift Engine server's JWT. The middleware only checks for the
 * cookie's PRESENCE to decide routing — the actual token validity is verified
 * by the server on every BFF call and by getCurrentUser() (GET /internal/v1/me).
 * That keeps the middleware dependency-free (no Supabase, no JWT verify) and
 * cheap, while a forged/expired cookie still fails at the real check.
 */
import { NextRequest, NextResponse } from "next/server";
import { legacyDomainRedirect } from "@/lib/legacy-domain";

const SESSION_COOKIE = "ml_session";

// Paths that require a logged-in user. Everything else is public.
const PRIVATE_PREFIXES = [
  "/dashboard",
  "/agents",
  "/settings",
  // /api routes proxy to the backend with the session JWT — they need the user.
  "/api/agents",
  "/api/api-keys",
];

function isPrivate(pathname: string): boolean {
  return PRIVATE_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Legacy-domain redirect (kept from the hosted reference instance; it only
  // fires for specific legacy hosts and is a no-op everywhere else). Done
  // first so it never depends on auth.
  const legacyTarget = legacyDomainRedirect(
    request.headers.get("host"),
    pathname + request.nextUrl.search,
  );
  if (legacyTarget) {
    return NextResponse.redirect(legacyTarget, 301);
  }

  // Static / Next internals — pass through.
  if (
    pathname.startsWith("/_next/") ||
    pathname === "/robots.txt" ||
    pathname === "/favicon.ico" ||
    pathname === "/favicon.svg" ||
    pathname === "/logo.svg"
  ) {
    return NextResponse.next();
  }

  // Pass the current pathname forward via a request header so the root layout
  // can read it (via next/headers) and decide whether to render the internal
  // nav (public verify pages get a stripped-down layout).
  request.headers.set("x-pathname", pathname);
  const response = NextResponse.next({ request });

  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);

  // Private route + no session → redirect to login with return path.
  if (isPrivate(pathname) && !hasSession) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("redirectTo", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Already logged in and visiting /login → bounce to dashboard.
  if (hasSession && pathname === "/login") {
    const dash = request.nextUrl.clone();
    dash.pathname = "/dashboard";
    dash.search = "";
    return NextResponse.redirect(dash);
  }

  return response;
}

export const config = {
  matcher: [
    // Match everything except next internals + a few well-known static files.
    "/((?!_next/static|_next/image|favicon.ico|favicon.svg|logo.svg|robots.txt).*)",
  ],
};
