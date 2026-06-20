/**
 * Proxy: DELETE /api/agents/[id]/webhooks/[webhookId] → Metalins.
 * Sprint UX-5.10-6.
 */
import { NextRequest, NextResponse } from "next/server";
import { deleteWebhook, ApiError } from "@/lib/api";

export async function DELETE(
  _request: NextRequest,
  {
    params,
  }: {
    params: Promise<{ id: string; webhookId: string }>;
  },
) {
  try {
    const { id, webhookId } = await params;
    await deleteWebhook(id, webhookId);
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
