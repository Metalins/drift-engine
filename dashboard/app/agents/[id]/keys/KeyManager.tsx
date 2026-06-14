/**
 * KeyManager — client component that runs the keys create/revoke flow.
 *
 * Lives client-side because we need state for:
 *   - The just-minted key (shown once, big copy-to-clipboard button)
 *   - Inline status (creating, revoking, error)
 *   - Local optimistic updates so the list reflects revoke immediately.
 *
 * All API calls go via /api/* proxy routes to avoid leaking the bearer
 * token to the client — those routes read the Supabase session cookie
 * server-side and forward to the Metalins server.
 */
"use client";

import { useState } from "react";
import type { ApiKeySummary } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/utils";

interface Props {
  agentId: string;
  initialKeys: ApiKeySummary[];
  /**
   * Optional callback fired right after a new key is minted, with the
   * plaintext secret in-hand. Used by the MCP setup page (Sprint
   * UX-5.15.K) to auto-fill the client-config snippets so the user
   * doesn't have to substitute `YOUR_METALINS_KEY` manually.
   *
   * Receives the same CreatedKey we put in the "copy now" panel; the
   * caller is responsible for clearing its own copy on dismiss.
   */
  onKeyMinted?: (key: CreatedKey) => void;
}

export interface CreatedKey extends ApiKeySummary {
  secret: string;
}

export function KeyManager({ agentId, initialKeys, onKeyMinted }: Props) {
  const [keys, setKeys] = useState<ApiKeySummary[]>(initialKeys);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "creating" }
    | { kind: "created"; key: CreatedKey }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const [revoking, setRevoking] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setStatus({ kind: "creating" });
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/api-keys`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, description: description || undefined }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const created = (await res.json()) as CreatedKey;
      setKeys([created, ...keys]);
      setStatus({ kind: "created", key: created });
      onKeyMinted?.(created);
      setName("");
      setDescription("");
      setShowCreate(false);
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  async function handleRevoke(keyId: string) {
    if (!confirm("Revoke this key? Any client using it will start failing.")) return;
    setRevoking(keyId);
    try {
      const res = await fetch(`/api/api-keys/${encodeURIComponent(keyId)}/revoke`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setKeys((prev) =>
        prev.map((k) =>
          k.id === keyId
            ? { ...k, is_active: false, revoked_at: new Date().toISOString() }
            : k,
        ),
      );
    } catch (err) {
      alert(
        `Could not revoke: ${err instanceof Error ? err.message : "Unknown error"}`,
      );
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          {keys.length} key{keys.length === 1 ? "" : "s"}
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Create new key
        </button>
      </div>

      {status.kind === "created" && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-4">
          <div className="text-sm font-medium">
            Copy this secret now — you won&apos;t see it again
          </div>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">
              {status.key.secret}
            </code>
            <button
              onClick={() => navigator.clipboard.writeText(status.key.secret)}
              className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
            >
              Copy
            </button>
          </div>
          <button
            onClick={() => setStatus({ kind: "idle" })}
            className="mt-3 text-xs text-muted-foreground underline"
          >
            I&apos;ve copied it — dismiss
          </button>
        </div>
      )}

      {showCreate && (
        <form
          onSubmit={handleCreate}
          className="space-y-3 rounded-md border bg-card p-4"
        >
          <div className="text-sm font-medium">New API key</div>
          <label className="block text-xs">
            Name
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. production, ci-bot"
              className="mt-1 block w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs">
            Description{" "}
            <span className="text-muted-foreground">(optional)</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="mt-1 block w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            />
          </label>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={status.kind === "creating" || !name.trim()}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {status.kind === "creating" ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowCreate(false);
                setStatus({ kind: "idle" });
              }}
              className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            >
              Cancel
            </button>
          </div>
          {status.kind === "error" && (
            <p className="text-sm text-destructive">{status.message}</p>
          )}
        </form>
      )}

      {keys.length === 0 ? (
        <p className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
          No keys yet. Click &ldquo;Create new key&rdquo; above to mint one.
        </p>
      ) : (
        <ul className="space-y-2">
          {keys.map((k) => (
            <li
              key={k.id}
              className="flex items-start justify-between gap-3 rounded-md border bg-card p-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">
                    {k.name ?? <em className="text-muted-foreground">unnamed</em>}
                  </span>
                  <Badge
                    variant={k.is_active ? "success" : "destructive"}
                  >
                    {k.is_active ? "active" : "revoked"}
                  </Badge>
                </div>
                {k.description && (
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {k.description}
                  </div>
                )}
                <div className="mt-1 text-xs text-muted-foreground">
                  created {timeAgo(k.created_at)}
                  {k.last_used_at
                    ? ` · last used ${timeAgo(k.last_used_at)}`
                    : " · never used"}
                  {k.revoked_at ? ` · revoked ${timeAgo(k.revoked_at)}` : ""}
                </div>
              </div>
              {k.is_active && (
                <button
                  onClick={() => handleRevoke(k.id)}
                  disabled={revoking === k.id}
                  className="rounded-md border px-2 py-1 text-xs text-destructive hover:bg-destructive/10 disabled:opacity-50"
                >
                  {revoking === k.id ? "Revoking…" : "Revoke"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
