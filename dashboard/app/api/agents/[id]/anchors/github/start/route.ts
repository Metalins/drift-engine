/**
 * Proxy: POST /api/agents/[id]/anchors/github/start → Metalins.
 * Sprint UX-5.9-G.
 */
import { NextRequest, NextResponse } from "next/server";
import { startGithubAnchor, ApiError } from "@/lib/api";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const result = await startGithubAnchor(id);
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
