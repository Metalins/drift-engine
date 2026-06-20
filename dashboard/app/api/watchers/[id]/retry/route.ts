/**
 * Proxy: POST /api/watchers/[id]/retry → Metalins retry-watcher.
 * Sprint UX-5.10-8.
 */
import { NextRequest, NextResponse } from "next/server";
import { retryWatcher, ApiError } from "@/lib/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await retryWatcher(id);
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
