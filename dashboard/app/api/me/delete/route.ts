/**
 * Proxy route for POST /v1/me/delete — account deletion.
 *
 * The dashboard's DeleteAccount component POSTs here; this handler
 * forwards to the backend with the Supabase-JWT bearer (server-side,
 * never exposing the token to the browser). The backend wipes every
 * row tied to the customer and writes one audit row.
 */
import { NextRequest, NextResponse } from "next/server";
import { ApiError, deleteAccount } from "@/lib/api";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const result = await deleteAccount(String(body?.reason ?? ""));
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof ApiError) {
      return NextResponse.json(
        { detail: err.message },
        { status: err.status },
      );
    }
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Unknown error" },
      { status: 500 },
    );
  }
}
