/**
 * POST /api/auth/change-password — proxies a password change to the Drift
 * Engine server's `POST /auth/change-password` (gh-119).
 *
 * Reads the session JWT from the httpOnly `ml_session` cookie and forwards it
 * as Bearer auth. The server requires the current password and clears the
 * `must_change_password` flag on success.
 */
import { NextRequest, NextResponse } from "next/server";
import { getAccessToken, serverApiUrl } from "@/lib/auth/server";

export async function POST(request: NextRequest) {
  const token = await getAccessToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated." }, { status: 401 });
  }

  let body: { current_password?: string; new_password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request body." }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${serverApiUrl()}/auth/change-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: body.current_password ?? "",
        new_password: body.new_password ?? "",
      }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { detail: "Could not reach the authentication server." },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    let detail = "Could not change password.";
    try {
      const err = await upstream.json();
      detail = err.detail || detail;
    } catch {
      // keep default
    }
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  return NextResponse.json({ ok: true });
}
