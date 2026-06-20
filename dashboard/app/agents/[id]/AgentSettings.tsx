"use client";

/**
 * AgentSettings — Sprint 4.11, hard-delete rewrite Sprint 5 (2026-05-14),
 * use_case selector + collapsible Sprint UX-5.11 R2 (2026-05-18).
 *
 * Two surfaces on the agent detail page:
 *   1. "Edit" panel: name / model / framework / use_case. Inline form,
 *      optimistic success message, errors surfaced clearly.
 *   2. "Danger zone": HARD delete this agent. Confirmation requires the
 *      user to type the exact agent name (GitHub style) before the
 *      destructive button enables. The server endpoint (POST /v1/agents/
 *      revoke — name kept for API compat) wipes the agent row plus all
 *      event_logs, agent_observables, memory_probes, watchers, verifications
 *      and scoped api_keys. Nothing stays in the database.
 *
 * use_case (bug-r1-andrea-2 follow-up): the value picked at agent
 * creation drives surface gating on /agents/[id]. We let customers
 * change it later because they might've picked wrong, or the agent's
 * role might evolve (a personal experiment graduating into a public
 * bot is a real progression). PATCH replaces metadata wholesale, so
 * we merge the new use_case onto the rest of the existing metadata
 * to preserve description/etc.
 *
 * Collapsible: per Jose's call, the whole settings + danger zone
 * panel lives inside a closed-by-default <details> at the bottom of
 * the agent page. Danger zone is one click away when needed, not
 * dominating the page when it isn't.
 *
 * Type-only imports from @/lib/api to keep this client bundle free of
 * server-only modules. All mutations go through /api proxy routes.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Save, X } from "lucide-react";
import {
  AGENT_PROFILE_OPTIONS,
  readAgentProfile,
  shortLabel as agentProfileLabel,
  type AgentProfile,
} from "@/lib/agent-profile";
import { ReissueSecretPanel } from "@/components/agents/ReissueSecretPanel";

interface Props {
  agentId: string;
  initialName: string;
  initialModel: string | null;
  initialFramework: string | null;
  initialMetadata: Record<string, unknown>;
  isActive: boolean;
  /**
   * Sprint UX-5.15.O. Tells the danger-zone modal which client-side
   * cleanup commands to surface BEFORE the user confirms the delete.
   * If we don't tell them, their Claude Code / Cursor / Desktop will
   * keep trying to log to a tombstone agent — see Jose's report when
   * `claude mcp list` showed a still-connected entry pointing at an
   * agent he had already removed.
   */
  integrationSurface: "watcher" | "mcp" | "sdk" | "none";
}

/**
 * Per-agent MCP server name. Mirrors McpQuickStart.mcpServerName so the
 * cleanup hint matches the connect command the user originally copied.
 */
function mcpServerName(agentName: string): string {
  const slug = agentName
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-+/g, "-")
    .slice(0, 40);
  return slug ? `metalins-${slug}` : "metalins";
}

export function AgentSettings({
  agentId,
  initialName,
  initialModel,
  initialFramework,
  initialMetadata,
  isActive,
  integrationSurface,
}: Props) {
  const router = useRouter();
  const initialProfile = readAgentProfile(initialMetadata);

  // ----- Edit panel state -----
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(initialName);
  const [model, setModel] = useState(initialModel ?? "");
  const [framework, setFramework] = useState(initialFramework ?? "");
  // Sprint UX-5.15.L — agent_profile is now editable from settings.
  // Legacy agents have null here; the <select> exposes the 3 options
  // so the customer can fix the value.
  const [profile, setProfile] = useState<AgentProfile | "">(
    initialProfile ?? "",
  );
  // gh-88 — "Memory probes" opt-in. Off by default. Hash-based probes only
  // make sense for deterministic agents (same input → same output); LLM
  // agents are stochastic and would always "fail" them. Reads probe_client
  // from metadata; written back as an explicit boolean on save.
  const [probesEnabled, setProbesEnabled] = useState<boolean>(
    Boolean(initialMetadata?.probe_client),
  );
  const [editStatus, setEditStatus] = useState<
    { kind: "idle" } | { kind: "saving" } | { kind: "saved" } | { kind: "error"; message: string }
  >({ kind: "idle" });

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setEditStatus({ kind: "error", message: "Name is required." });
      return;
    }
    setEditStatus({ kind: "saving" });
    try {
      // Backend's PATCH /v1/agents/{id} replaces metadata wholesale
      // (see app/api/agents.py:287). We merge new fields onto the
      // existing metadata so others like description survive.
      // UX-5.15.AD — `use_case` is no longer written; legacy values
      // already in metadata are left untouched (harmless, ignored).
      const mergedMetadata: Record<string, unknown> = { ...initialMetadata };
      // Wholesale-replace dance for agent_profile (UX-5.15.L).
      if (profile) {
        mergedMetadata.agent_profile = profile;
      } else {
        delete mergedMetadata.agent_profile;
      }
      // gh-88 — persist the Memory probes opt-in as an explicit boolean so
      // turning it off survives the wholesale metadata replace.
      mergedMetadata.probe_client = probesEnabled;
      const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          model: model.trim(),
          framework: framework.trim(),
          metadata: mergedMetadata,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setEditStatus({ kind: "saved" });
      setEditing(false);
      router.refresh();
    } catch (err) {
      setEditStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  function cancelEdit() {
    setName(initialName);
    setModel(initialModel ?? "");
    setFramework(initialFramework ?? "");
    setProfile(initialProfile ?? "");
    setProbesEnabled(Boolean(initialMetadata?.probe_client));
    setEditStatus({ kind: "idle" });
    setEditing(false);
  }

  // ----- Danger zone state -----
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const canRevoke = confirmText === initialName && !revoking;

  async function handleRevoke() {
    if (!canRevoke) return;
    setRevoking(true);
    setRevokeError(null);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/revoke`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: "Deleted via dashboard" }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      // Redirect to the agent list — the detail page would now show a
      // revoked state but it's friendlier to bounce back to /dashboard.
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "Unknown error");
      setRevoking(false);
    }
  }

  return (
    // Sprint UX-5.11 R2 (2026-05-18): the entire settings + danger
    // zone block lives inside a closed-by-default <details> so the
    // bottom of the agent page is calm. Editing name / use_case /
    // deleting is one click away when you need it, not in your face
    // when you don't.
    <details className="group rounded-lg border bg-card/40">
      <summary className="flex cursor-pointer items-center justify-between gap-3 px-5 py-3 text-sm font-medium hover:bg-accent/40">
        <span>Agent settings &amp; danger zone</span>
        <span className="text-xs text-muted-foreground group-open:hidden">
          Click to expand
        </span>
        <span className="hidden text-xs text-muted-foreground group-open:inline">
          Click to collapse
        </span>
      </summary>

      <section className="space-y-6 border-t p-5">
        {/* ----- Edit panel ------------------------------------------- */}
        <div className="rounded-lg border bg-card p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
              Settings
            </h2>
            {isActive && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="text-xs font-medium text-foreground underline-offset-4 hover:underline"
              >
                Edit
              </button>
            )}
          </div>

          {!editing && (
            <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
              <div>
                <dt className="text-xs text-muted-foreground">Name</dt>
                <dd className="mt-0.5 font-medium">{initialName}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">
                  Answer variability
                </dt>
                <dd className="mt-0.5 font-medium">
                  {initialProfile ? (
                    agentProfileLabel(initialProfile)
                  ) : (
                    <span className="text-muted-foreground">
                      Not specified
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Model</dt>
                <dd className="mt-0.5 font-medium">
                  {initialModel ?? <span className="text-muted-foreground">—</span>}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Framework</dt>
                <dd className="mt-0.5 font-medium">
                  {initialFramework ?? <span className="text-muted-foreground">—</span>}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Memory probes</dt>
                <dd className="mt-0.5 font-medium">
                  {probesEnabled ? (
                    "On"
                  ) : (
                    <span className="text-muted-foreground">Off</span>
                  )}
                </dd>
              </div>
            </dl>
          )}

        {editing && (
          <form onSubmit={handleSave} className="mt-4 space-y-4">
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
                required
                className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            {/* UX-5.15.AD: use_case selector removed. The concept
                used to gate which sections appeared on the agent
                page; gating is gone, so the selector has nothing to
                drive. Customers no longer have to pick (or rectify)
                a "what's this agent for" up front. */}
            {/* Sprint UX-5.15.L — agent_profile editor. Switching this
                changes which impostor checks apply (deterministic-only
                checks light up when "Strict / reproducible" is picked,
                stay dark otherwise). We warn the customer up front so
                they don't toggle it casually. */}
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                Answer variability
              </span>
              <select
                value={profile}
                onChange={(e) => setProfile(e.target.value as AgentProfile | "")}
                className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">— Not specified (legacy default) —</option>
                {AGENT_PROFILE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-muted-foreground">
                Changes which impostor checks apply. Match this to how
                your agent actually behaves &mdash; a wrong pick gives
                false alarms or weaker detection.
              </span>
              {profile && initialProfile && profile !== initialProfile && (
                <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
                  Changing this rewires which protections are active
                  for this agent. Existing event history stays; the new
                  protection set takes effect on the next score
                  refresh.
                </div>
              )}
            </label>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="text-xs font-medium text-muted-foreground">Model</span>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. claude-sonnet-4-6"
                  className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-muted-foreground">Framework</span>
                <input
                  type="text"
                  value={framework}
                  onChange={(e) => setFramework(e.target.value)}
                  placeholder="e.g. claude-code"
                  className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
            </div>

            {/* gh-88 — Memory probes opt-in. OFF by default. Hash-based
                round-trip probes only work for deterministic agents; for
                LLM-based (stochastic) agents they always fail and raise a
                false "memory checks failing" alarm. The behavioral engine
                is the right mechanism there. */}
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={probesEnabled}
                onChange={(e) => setProbesEnabled(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-input text-primary focus:ring-2 focus:ring-ring"
              />
              <span className="block">
                <span className="text-xs font-medium text-muted-foreground">
                  Memory probes
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Enable only if your agent is deterministic &mdash; the same
                  input always produces the same output. Not recommended for
                  LLM-based agents, whose answers vary from one run to the
                  next: memory checks would always fail and raise false
                  alarms. Behavioral monitoring covers those agents instead.
                </span>
              </span>
            </label>

            {editStatus.kind === "error" && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {editStatus.message}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={cancelEdit}
                disabled={editStatus.kind === "saving"}
                className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
              >
                <X size={14} />
                Cancel
              </button>
              <button
                type="submit"
                disabled={editStatus.kind === "saving"}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
              >
                <Save size={14} />
                {editStatus.kind === "saving" ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        )}
        </div>

        {/* ----- Re-issue secret (UX-5.17 #505) ----------------------- */}
        {isActive && (
          <ReissueSecretPanel agentId={agentId} agentName={initialName} />
        )}

        {/* ----- Danger zone ------------------------------------------ */}
        {isActive && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
          <div className="flex items-start gap-3">
            <AlertTriangle size={20} className="mt-0.5 shrink-0 text-destructive" />
            <div className="flex-1 space-y-2">
              <h2 className="font-medium text-destructive">Danger zone</h2>
              <p className="text-sm text-muted-foreground">
                Deleting an agent <strong>permanently removes</strong> it
                and <strong>all</strong> its data from our database — every
                event, identity snapshot, memory check, connected bot and
                scoped API key. We do <strong>not</strong> keep an audit
                copy. Future verifications for this agent will return 404.
                This action cannot be undone.
              </p>
              {!confirmOpen && (
                <button
                  onClick={() => setConfirmOpen(true)}
                  className="mt-2 rounded-md border border-destructive/50 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10"
                >
                  Delete this agent
                </button>
              )}
            </div>
          </div>

          {/* Confirmation modal (inline panel, not a real <dialog>) */}
          {confirmOpen && (
            <div className="mt-4 space-y-3 rounded-md border border-destructive/40 bg-background p-4">
              {/* Sprint UX-5.15.O — pre-delete cleanup instructions.
                  Jose's report: after deleting an agent, his MCP client
                  kept the server entry and silently sent events to a
                  tombstone. The fix is to surface the cleanup commands
                  HERE — right when the user is committing the delete —
                  scoped to the integration this agent actually used. */}
              {integrationSurface === "mcp" && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
                  <div className="font-medium text-foreground">
                    Before deleting: clean up your client
                  </div>
                  <p className="mt-1 text-muted-foreground">
                    Your AI client (Claude Code / Cursor / Claude
                    Desktop) still has a connector pointing at this
                    agent. After the delete it will keep trying to log
                    events &mdash; harmless, but noisy. Run this in your
                    terminal:
                  </p>
                  <pre className="mt-2 overflow-x-auto rounded bg-muted/50 p-2 font-mono text-[11px]">
                    <code>
                      claude mcp remove {mcpServerName(initialName)} --scope user
                    </code>
                  </pre>
                  <p className="mt-2 text-muted-foreground">
                    For Cursor, remove the matching entry from{" "}
                    <code className="rounded bg-muted px-1 py-0.5">
                      ~/.cursor/mcp.json
                    </code>
                    . For Claude Desktop, open Settings → Connectors
                    and delete the entry.
                  </p>
                </div>
              )}
              {integrationSurface === "watcher" && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
                  <div className="font-medium text-foreground">
                    Before deleting: turn off the bot poller
                  </div>
                  <p className="mt-1 text-muted-foreground">
                    Metalins polls your Telegram bot every few seconds.
                    The poller stops automatically when the agent is
                    deleted &mdash; you don&apos;t need to do anything
                    on Telegram. The bot itself stays untouched.
                  </p>
                </div>
              )}
              {integrationSurface === "none" && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-muted-foreground">
                  This agent never connected to a client. Nothing
                  external to clean up &mdash; just confirm the
                  delete.
                </div>
              )}

              <p className="text-sm">
                To confirm, type{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs font-medium text-foreground">
                  {initialName}
                </code>{" "}
                below.
              </p>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={initialName}
                autoFocus
                className="block w-full rounded-md border bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-destructive"
              />
              {revokeError && (
                <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                  {revokeError}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => {
                    setConfirmOpen(false);
                    setConfirmText("");
                    setRevokeError(null);
                  }}
                  disabled={revoking}
                  className="rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRevoke}
                  disabled={!canRevoke}
                  className="rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {revoking ? "Deleting..." : "I understand, delete permanently"}
                </button>
              </div>
            </div>
          )}
          </div>
        )}
      </section>
    </details>
  );
}
