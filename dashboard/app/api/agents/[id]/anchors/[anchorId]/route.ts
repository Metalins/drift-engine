/**
 * Proxy: DELETE /api/agents/[id]/anchors/[anchorId] → Metalins.
 * Sprint UX-5.9-G.
 */
import { NextRequest, NextResponse } from "next/server";
import { deleteAnchor, ApiError } from "@/lib/api";

export async function DELETE(
  _request: NextRequest,
  {
    params,
  }: {
    params: Promise<{ id: string; anchorId: string }>;
  },
) {
  try {
    const { id, anchorId } = await params;
    await deleteAnchor(id, anchorId);
    return new NextResponse(null, { status: 204 });
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
