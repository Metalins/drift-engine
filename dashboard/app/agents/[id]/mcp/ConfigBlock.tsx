/**
 * ConfigBlock — labeled code block with a Copy button + optional
 * "replace YOUR_API_KEY" hint. Shared between the dense `/mcp`
 * page and the step-by-step `/mcp/setup` wizard so the snippet layout
 * stays consistent (Sprint UX-5.15.T).
 */
"use client";

import { CopyButton } from "./CopyButton";
import { PLACEHOLDER } from "@/lib/mcp-snippets";

interface Props {
  title: string;
  description: string;
  code: string;
  copyLabel: string;
  /** When false, render the "replace YOUR_API_KEY" hint below. */
  hasRealKey: boolean;
}

export function ConfigBlock({
  title,
  description,
  code,
  copyLabel,
  hasRealKey,
}: Props) {
  return (
    <div className="rounded-md border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{title}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{description}</div>
        </div>
        <CopyButton value={code} label={copyLabel} />
      </div>
      <pre className="mt-3 overflow-x-auto rounded bg-background p-3 text-xs leading-relaxed">
        <code>{code}</code>
      </pre>
      {!hasRealKey && (
        <p className="mt-2 text-xs text-muted-foreground">
          Replace{" "}
          <code className="rounded bg-muted px-1 py-0.5">{PLACEHOLDER}</code>{" "}
          with the plaintext from step 2. Or mint a key now and we&apos;ll
          inline it here automatically.
        </p>
      )}
    </div>
  );
}
