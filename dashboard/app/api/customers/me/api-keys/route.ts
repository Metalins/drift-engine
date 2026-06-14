/**
 * Proxy routes for /v1/customers/me/api-keys.
 *
 * Sprint UX-5.11 / bug-andrea-3 (2026-05-17). Lets the dashboard list
 * AND create customer-wide API keys via the same Supabase-JWT bearer
 * the rest of the app uses, without leaking the token to the browser.
 *
 *   GET  /api/customers/me/api-keys                 → listCustomerKeys
 *   POST /api/customers/me/api-keys                 → createCustomerKey
 *   ?include_revoked=true on GET to include revoked keys
 */
import { NextRequest, NextResponse } from "next/server";
import { ApiError, createCustomerKey, listCustomerKeys } from "@/lib/api";

export async function GET(request: NextRequest) {
  try {
    const include = request.nextUrl.searchParams.get("include_revoked") === "true";
    const result = await listCustomerKeys({ includeRevoked: include });
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

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const result = await createCustomerKey({
      name: body.name,
      description: body.description,
    });
    return NextResponse.json(result, { status: 201 });
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
