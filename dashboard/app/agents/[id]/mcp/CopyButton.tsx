/**
 * CopyButton — shared UI primitive used by the dense `/mcp` page and
 * the step-by-step `/mcp/setup` wizard (Sprint UX-5.15.T). Both render
 * snippets the customer copies into their MCP client; both want the
 * same "Copy → Copied" affordance with a 1.8s flip.
 */
"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

interface Props {
  value: string;
  label: string;
}

export function CopyButton({ value, label }: Props) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1800);
        } catch {
          /* ignore — older browsers without secure context */
        }
      }}
      className="inline-flex items-center gap-1.5 rounded-md border bg-background px-2.5 py-1 text-xs font-medium hover:bg-accent"
    >
      {copied ? (
        <>
          <Check size={12} className="text-emerald-600" />
          Copied
        </>
      ) : (
        <>
          <Copy size={12} />
          {label}
        </>
      )}
    </button>
  );
}
