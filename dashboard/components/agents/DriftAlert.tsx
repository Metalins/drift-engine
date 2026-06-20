"use client";

/**
 * DriftAlert — UX-5.15.P / D-PROD.25.
 *
 * Pedagogical alert that renders as the primary surface on /agents/[id]
 * when the behavioral layer reports drift. The lifecycle doc rector
 * (docs/product/INTEGRATION-LIFECYCLE.md §5) lays out the principle:
 * Metalins detects the change and asks; the human is the oracle.
 *
 * The customer sees a list of common reasons their agent's behavior
 * might have shifted (compaction, project change, new machine,
 * impostor) and chooses between:
 *   - "Yes, this is the new normal" → calls reset-baseline
 *   - "No, I didn't expect this" → leaves the score low for investigation
 *
 * Anti-receta: this component never displays what the expected shape
 * looks like. The hypotheses are generic ("you compacted", "new
 * project") not derived from the agent's data. The LLM/MCP client
 * sees none of this — it's strictly dashboard-owner UI.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { AgentAlert } from "./AgentAlert";

interface DriftAlertProps {
  agentId: string;
  agentName: string;
}

const HYPOTHESES = [
  "You compacted your conversation (Claude /compact, Cursor cleanup, etc.)",
  "You started a new project or changed your system prompt",
  "You connected from a different machine or after a long pause",
  "Someone other than you is using your agent (less common)",
];

export function DriftAlert({ agentId, agentName }: DriftAlertProps) {
  const router = useRouter();
  const [mode, setMode] = useState<"prompt" | "confirm-reset" | "investigate">(
    "prompt",
  );
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleReset() {
    setBusy(true);
    setError(null);
    try {
      // Local proxy — avoid importing lib/api directly into a client
      // bundle because lib/api pulls in @supabase/ssr server cookies.
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/reset-baseline`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_name: agentName }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body && (body.detail || body.error)) ||
            `Reset failed (${res.status}).`,
        );
      }
      // Refresh server data — the trust block should drop drift_detected.
      router.refresh();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not reset baseline.",
      );
      setBusy(false);
    }
  }

  return (
    <AgentAlert
      severity="attention"
      ariaLabel="Behavior change detected"
      title={
        <>
          Your agent <span className="font-bold">{agentName}</span> changed
          significantly
        </>
      }
    >
      {mode === "prompt" && (
            <>
              <p className="text-sm leading-relaxed text-foreground/90">
                Its recent behavior doesn&apos;t match the pattern we
                learned. This usually happens because of one of these:
              </p>
              <ul className="ml-5 list-disc space-y-1 text-sm text-foreground/80">
                {HYPOTHESES.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
              <p className="pt-2 text-sm font-medium text-foreground">
                Is this something you expected?
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setMode("confirm-reset")}
                  className="inline-flex items-center rounded-md border border-foreground/20 bg-background px-4 py-2 text-sm font-medium hover:bg-muted"
                >
                  Yes, this is the new normal
                </button>
                <button
                  type="button"
                  onClick={() => setMode("investigate")}
                  className="inline-flex items-center rounded-md border border-foreground/20 px-4 py-2 text-sm font-medium hover:bg-muted/50"
                >
                  No, I didn&apos;t expect this
                </button>
              </div>
            </>
          )}

          {mode === "confirm-reset" && (
            <>
              <p className="text-sm leading-relaxed text-foreground/90">
                We&apos;ll accept the new behavior as the baseline going
                forward. Your past events stay archived as evidence —
                they&apos;re not deleted. From now on the score is
                measured against this new pattern.
              </p>
              <p className="text-sm text-foreground/80">
                Type the agent name{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs font-semibold">
                  {agentName}
                </code>{" "}
                to confirm.
              </p>
              <input
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={agentName}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                autoFocus
                disabled={busy}
              />
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={typed !== agentName || busy}
                  className="inline-flex items-center gap-1.5 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy && <Loader2 size={14} className="animate-spin" />}
                  Reset baseline
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMode("prompt");
                    setTyped("");
                    setError(null);
                  }}
                  disabled={busy}
                  className="rounded-md px-4 py-2 text-sm font-medium hover:bg-muted/50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}

          {mode === "investigate" && (
            <>
              <p className="text-sm leading-relaxed text-foreground/90">
                The score stays low while you investigate. If you suspect
                someone else is using the agent, you can pause the MCP
                surface from the settings below — that stops new events
                from being accepted on the server side until you resume.
              </p>
              <p className="text-sm text-foreground/80">
                If you change your mind and decide the new behavior is
                fine, come back here and accept the new normal.
              </p>
              <button
                type="button"
                onClick={() => setMode("prompt")}
                className="rounded-md border border-foreground/20 px-4 py-2 text-sm font-medium hover:bg-muted/50"
              >
                ← Back to options
              </button>
            </>
          )}
    </AgentAlert>
  );
}
