"use client";

/**
 * ProfileMismatchAlert — UX-5.15.AM (2026-05-21).
 *
 * The first alert that carries an EXECUTABLE action — the product
 * pattern "detect → explain → offer an executable action". The engine
 * flagged that the agent's declared behavior setting (agent_profile)
 * contradicts how it actually behaves; this card explains it and offers
 * a one-click fix that PATCHes the profile, no trip to settings.
 *
 * Renders through the shared <AgentAlert> shell like DriftAlert /
 * WatcherAlert, so the chrome stays homogeneous. Severity comes from the
 * issue: "attention" (amber) when the customer over-declared rigidity
 * (the dangerous direction — strict checks false-positive), "info"
 * (calm blue) when they under-declared (an upgrade opportunity).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { SlidersHorizontal } from "lucide-react";
import { AgentAlert } from "./AgentAlert";
import type { AgentDetail } from "@/lib/api";
import type { AgentIssue } from "@/lib/agent-issues";
import { shortLabel, type AgentProfile } from "@/lib/agent-profile";

export function ProfileMismatchAlert({
  agent,
  issue,
}: {
  agent: AgentDetail;
  issue: AgentIssue;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<
    { kind: "idle" } | { kind: "saving" } | { kind: "error"; message: string }
  >({ kind: "idle" });

  const suggested = issue.suggestedProfile as AgentProfile | undefined;
  if (!suggested) return null;
  const message = issue.paragraphs?.[0] ?? "";

  async function applyProfile() {
    setStatus({ kind: "saving" });
    try {
      // Mirror AgentSettings' PATCH: the backend replaces metadata
      // wholesale, so we merge the new agent_profile onto the existing
      // metadata and resend name / model / framework unchanged.
      const merged: Record<string, unknown> = {
        ...agent.metadata,
        agent_profile: suggested,
      };
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agent.agent_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: agent.name,
            model: agent.model ?? "",
            framework: agent.framework ?? "",
            metadata: merged,
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      // The factor clears on the next recompute once the new profile is
      // in effect; refresh so the rest of the page reflects the change.
      router.refresh();
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  return (
    <AgentAlert
      severity={issue.severity}
      title="This agent's behavior doesn't match its declared setting."
      icon={<SlidersHorizontal size={22} />}
      ariaLabel="Behavior setting mismatch"
    >
      <p className="text-sm leading-relaxed text-foreground/90">{message}</p>
      {/* UX-5.17 #930 — the `attention` direction (declared stricter than
          observed) is genuinely ambiguous: a real behavior change can look
          identical to a too-strict setting. The one-click switch must not
          read as "dismiss this false alarm" — gate it with the condition
          so a customer doesn't reflexively silence a compromise signal. */}
      {issue.severity === "attention" && (
        <p className="text-xs text-muted-foreground">
          Only switch the setting if you expected this behavior change. If
          you didn&apos;t, investigate first — switching it would hide the
          signal.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          onClick={applyProfile}
          disabled={status.kind === "saving"}
          className="inline-flex items-center rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90 disabled:opacity-60"
        >
          {status.kind === "saving"
            ? "Updating…"
            : `Change setting to “${shortLabel(suggested)}”`}
        </button>
        {status.kind === "error" && (
          <span className="text-xs text-destructive">{status.message}</span>
        )}
      </div>
    </AgentAlert>
  );
}
