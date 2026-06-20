/**
 * POST /api/auth/login — self-hosted login (gh-119).
 *
 * Proxies email+password to the Drift Engine server's `POST /auth/login`,
 * and on success stores the returned session JWT in an httpOnly cookie
 * (`ml_session`). The browser never sees the JWT directly — it lives only in
 * the cookie, which is sent automatically on subsequent requests and read
 * server-side by lib/auth/server.ts.
 */
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, serverApiUrl } from "@/lib/auth/server";

interface LoginResult {
  access_token: string;
  token_type: string;
  must_change_password?: boolean;
  email?: string;
}

export async function POST(request: NextRequest) {
  let body: { email?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body." }, { status: 400 });
  }

  const email = (body.email || "").trim();
  const password = body.password || "";
  if (!email || !password) {
    return NextResponse.json(
      { detail: "Email and password are required." },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${serverApiUrl()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the authentication server." },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    let detail = "Invalid email or password.";
    try {
      const err = await upstream.json();
      detail = err.detail || detail;
    } catch {
      // keep default
    }
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  const data = (await upstream.json()) as LoginResult;

  const response = NextResponse.json({
    ok: true,
    must_change_password: Boolean(data.must_change_password),
    email: data.email ?? email,
  });

  // httpOnly session cookie. Not Secure here so it works over plain HTTP in a
  // self-hosted docker-compose (no TLS termination by default); operators
  // fronting this with HTTPS can add it. SameSite=Lax is enough for a
  // first-party dashboard.
  response.cookies.set({
    name: SESSION_COOKIE,
    value: data.access_token,
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    // Match the server's session JWT TTL (24h, settings.auth_jwt_ttl_seconds)
    // so the cookie disappears exactly when the token expires — otherwise the
    // middleware would still see a "present" cookie and let the user onto a
    // private page whose first /me call then 401s.
    maxAge: 60 * 60 * 24,
  });

  return response;
}
