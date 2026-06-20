/**
 * Proxy: POST /api/agents/[id]/watchers → Metalins create-watcher.
 * Forwards the body verbatim with the Supabase session JWT as bearer.
 */
import { NextRequest, NextResponse } from "next/server";
import { createWatcher, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = await request.json();
    const result = await createWatcher(id, {
      platform: body.platform,
      token: body.token,
      display_name: body.display_name,
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
