/**
 * /auth/signout — clears the session cookie and redirects to /login.
 *
 * Used by the account header's signout button (POSTed via a plain HTML form
 * to avoid shipping client JS just for this). Self-hosting pivot (gh-119):
 * there is no Supabase session to revoke — dropping the httpOnly `ml_session`
 * cookie is the whole logout. The server-minted JWT expires on its own.
 */
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth/server";

export async function POST(request: NextRequest) {
  const { origin } = new URL(request.url);
  const response = NextResponse.redirect(`${origin}/login`, { status: 303 });
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
