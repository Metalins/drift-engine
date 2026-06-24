"use client";

/**
 * McpDisconnectButton — Sprint 6.4 / #575.
 *
 * Renamed in UX-5.15.P / D-PROD.25: customer-facing copy is now
 * "Pause MCP surface" / "Resume MCP surface" instead of
 * "Disconnect" / "Reconnect", because the action is *server-side
 * only* — we stop accepting events, but we don't touch the client's
 * `~/.claude.json` / Cursor `mcp.json` / Connectors entry. The old
 * "Disconnect" copy was misleading users into thinking we'd clean
 * up their client config too. See docs/product/INTEGRATION-LIFECYCLE.md §4.
 *
 * Backend endpoints keep the legacy /disconnect-mcp /reconnect-mcp
 * paths intentionally so existing integrations don't break.
 *
 * Historical EventLog rows are preserved — this is a gate on new
 * ingestion, not a wipe (D-PROD.18 / Sprint 6.4 plan).
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Plug, Unplug } from "lucide-react";

interface Props {
  agentId: string;
  agentName: string;
  isDisconnected: boolean;
}

export function McpDisconnectButton({
  agentId,
  agentName,
  isDisconnected,
}: Props) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canDisconnect = confirmText === agentName && !busy && !pending;

  async function callDisconnect() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/disconnect-mcp`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_name: agentName }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      setConfirmOpen(false);
      setConfirmText("");
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  async function callReconnect() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/reconnect-mcp`,
        { method: "POST" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  if (isDisconnected) {
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
        <div className="flex items-start gap-3">
          <Unplug
            size={20}
            className="mt-0.5 shrink-0 text-amber-700 dark:text-amber-400"
          />
          <div className="flex-1 space-y-2">
            <h3 className="text-sm font-medium text-amber-900 dark:text-amber-200">
              MCP surface is paused
            </h3>
            <p className="text-sm text-muted-foreground">
              Drift Engine is rejecting new events for this agent (your
              client gets a 403). Your client config still has the
              entry — Resume below to start accepting again. Existing
              event history is preserved either way.
            </p>
            <button
              onClick={callReconnect}
              disabled={busy || pending}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plug size={14} />
              {busy ? "Resuming…" : "Resume MCP surface"}
            </button>
            {error && (
              <p className="text-xs text-destructive">{error}</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle
          size={20}
          className="mt-0.5 shrink-0 text-destructive"
        />
        <div className="flex-1 space-y-2">
          <h3 className="text-sm font-medium text-destructive">
            Pause MCP surface
          </h3>
          <p className="text-sm text-muted-foreground">
            Stops the server from accepting new events for this agent.
            Your client config (Claude Code, Cursor, Claude Desktop)
            stays as it is — remove it manually if you want to. The
            historical event log is preserved. Resume at any time.
            Use this if your API key got exposed and you need to
            freeze right now, or if you&apos;re parking the project
            for a while.
          </p>
          {!confirmOpen && (
            <button
              onClick={() => setConfirmOpen(true)}
              className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-destructive/50 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10"
            >
              <Unplug size={14} />
              Pause MCP surface
            </button>
          )}
        </div>
      </div>

      {confirmOpen && (
        <div className="mt-4 space-y-3 rounded-md border border-destructive/40 bg-background p-4">
          <p className="text-sm">
            To confirm, type{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs font-medium text-foreground">
              {agentName}
            </code>{" "}
            below.
          </p>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={agentName}
            autoFocus
            className="block w-full rounded-md border bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-destructive"
          />
          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => {
                setConfirmOpen(false);
                setConfirmText("");
                setError(null);
              }}
              disabled={busy}
              className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={callDisconnect}
              disabled={!canDisconnect}
              className="rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Pausing…" : "Pause MCP surface"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
