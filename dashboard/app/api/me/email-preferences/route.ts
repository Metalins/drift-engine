/**
 * Proxy routes for /v1/me/email-preferences.
 *
 * Sprint UX-5.13.E.5 (2026-05-18). Lets the dashboard's
 * EmailPreferencesForm read + write the customer's outbound email
 * preferences via the same Supabase-JWT bearer the rest of the app
 * uses, without leaking the token to the browser.
 *
 *   GET   /api/me/email-preferences   → getEmailPreferences
 *   PATCH /api/me/email-preferences   → updateEmailPreferences
 */
import { NextRequest, NextResponse } from "next/server";
import { ApiError, getEmailPreferences, updateEmailPreferences } from "@/lib/api";

export async function GET() {
  try {
    const result = await getEmailPreferences();
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Unknown error" },
      { status: 500 },
    );
  }
}

export async function PATCH(request: NextRequest) {
  try {
    const body = await request.json();
    const result = await updateEmailPreferences(body);
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Unknown error" },
      { status: 500 },
    );
  }
}
