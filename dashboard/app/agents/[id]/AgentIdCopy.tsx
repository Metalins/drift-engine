"use client";

import { useState } from "react";

/**
 * Tiny client component: a "Copy ID" pill that reveals/copies the
 * internal agent_id without dumping it into the visible subtitle. Sprint
 * UX-5.15.J Fix 5 — Andrea has no use for the raw `agt_xxxx` string,
 * but power users + support tickets need it. The pill stays small and
 * unobtrusive while keeping the ID one click away.
 */
export function AgentIdCopy({ agentId }: { agentId: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(agentId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // best-effort; some browsers gate clipboard access. The title
      // attribute still exposes the full ID so the user can copy
      // manually if needed.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={`Agent ID: ${agentId}\nClick to copy`}
      className="inline-flex items-center gap-1 rounded border border-neutral-300 bg-neutral-50 px-2 py-0.5 text-[11px] font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:border-neutral-600 dark:hover:bg-neutral-800"
      aria-label={copied ? "Agent ID copied" : "Copy agent ID"}
    >
      <span aria-hidden>{copied ? "✓" : "ID"}</span>
      <span>{copied ? "copied" : "copy"}</span>
    </button>
  );
}
