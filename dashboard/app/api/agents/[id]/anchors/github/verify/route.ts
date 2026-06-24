/**
 * Proxy: POST /api/agents/[id]/anchors/github/verify → Metalins.
 * Sprint UX-5.9-G.
 */
import { NextRequest, NextResponse } from "next/server";
import { verifyGithubAnchor, ApiError } from "@/lib/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const body = (await request.json()) as {
      anchor_id: string;
      gist_url: string;
    };
    const result = await verifyGithubAnchor(id, body);
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
