"use client";

/**
 * AnchorsManager — Client Component driving the anchor flows.
 *
 * Sprint UX-5.9-G (GitHub gist) + Sprint UX-5.11 R2 / bug-r1-carlos-1
 * (Telegram bio, 2026-05-18). Both flows are two-step:
 *
 *   1. Click "Start <type> anchor" → server mints a challenge token.
 *      We show the token + instructions.
 *   2. User submits the proof location (gist URL or @username) → we
 *      POST /verify which fetches the external evidence, validates the
 *      token, and persists value=<owner_login | @username>.
 *
 * Important: this is a Client Component, so we CANNOT import from
 * `@/lib/api` — those helpers call into `next/headers` (Supabase
 * session cookie reader), which Turbopack refuses to bundle into a
 * client component. Instead we fetch our own Next route handlers at
 * `/api/agents/[id]/anchors/*`, which run on the server and call the
 * Metalins backend with the user's session.
 */
import { useState } from "react";

// Local mirror of the AnchorRow shape so we don't import from
// `@/lib/api` (which is server-only). Keep in sync with that file.
interface AnchorRow {
  id: string;
  type: string;
  method: string;
  value: string | null;
  verified_at: string | null;
  created_at: string | null;
  last_check_at: string | null;
}

interface StartResponse {
  anchor_id: string;
  challenge_token: string;
  instructions: string;
}

interface Props {
  agentId: string;
  initialAnchors: AnchorRow[];
  /**
   * The agent's current public_slug (or null if it doesn't have one).
   * Sprint UX-5.11 R2 / R2.3e. Used to decide whether the verified-
   * anchor list should offer a "Claim as public URL" button next to
   * each row.
   */
  initialSlug: string | null;
}

/** Lightweight slugifier mirroring server/app/core/slug.py::slugify.
 *  We use this to (a) preview the slug a "Claim" click would produce
 *  and (b) decide which anchor in the verified list is currently the
 *  source of the agent's public_slug. The backend still owns the
 *  authoritative normalization. */
function previewSlug(value: string | null): string {
  if (!value) return "";
  return value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "") // strip combining marks
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/^-+|-+$/g, "");
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

// Shape of the pending state for either flow. We track which flow the
// token belongs to so we hit the right /verify endpoint and so the
// inline "Cancel" button removes only the right pending anchor.
interface PendingState {
  kind: "github" | "telegram";
  anchorId: string;
  challengeToken: string;
  instructions: string;
}

export function AnchorsManager({
  agentId,
  initialAnchors,
  initialSlug,
}: Props) {
  const [anchors, setAnchors] = useState<AnchorRow[]>(initialAnchors);
  // Sprint UX-5.11 R2 / R2.3e — track the current slug locally so the
  // "Claim as public URL" button can disable for the active source and
  // update after a successful claim without a full page reload.
  const [currentSlug, setCurrentSlug] = useState<string | null>(initialSlug);
  // Two independent pending slots — Carlos may be in the middle of
  // proving GitHub AND Telegram at the same time. Tracking them
  // separately avoids losing the GitHub token if he clicks "Start
  // Telegram" mid-flight (and vice versa).
  const [pendingGithub, setPendingGithub] = useState<PendingState | null>(null);
  const [pendingTelegram, setPendingTelegram] = useState<PendingState | null>(null);
  const [gistUrl, setGistUrl] = useState("");
  const [telegramUsername, setTelegramUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshList(): Promise<AnchorRow[]> {
    const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/anchors`);
    const data = await jsonOrThrow<{ anchors: AnchorRow[] }>(res);
    return data.anchors;
  }

  async function startFlow(kind: "github" | "telegram") {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/anchors/${kind}/start`,
        { method: "POST" },
      );
      const data = await jsonOrThrow<StartResponse>(res);
      const pending: PendingState = {
        kind,
        anchorId: data.anchor_id,
        challengeToken: data.challenge_token,
        instructions: data.instructions,
      };
      if (kind === "github") setPendingGithub(pending);
      else setPendingTelegram(pending);
      setAnchors(await refreshList());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyGithub() {
    if (!pendingGithub) return;
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/anchors/github/verify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            anchor_id: pendingGithub.anchorId,
            gist_url: gistUrl.trim(),
          }),
        },
      );
      const row = await jsonOrThrow<AnchorRow>(res);
      setAnchors((prev) => [row, ...prev.filter((a) => a.id !== row.id)]);
      setPendingGithub(null);
      setGistUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyTelegram() {
    if (!pendingTelegram) return;
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/anchors/telegram/verify`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            anchor_id: pendingTelegram.anchorId,
            telegram_username: telegramUsername.trim(),
          }),
        },
      );
      const row = await jsonOrThrow<AnchorRow>(res);
      setAnchors((prev) => [row, ...prev.filter((a) => a.id !== row.id)]);
      setPendingTelegram(null);
      setTelegramUsername("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleClaimSlug(anchorId: string) {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/claim-slug`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ anchor_id: anchorId }),
        },
      );
      const data = await jsonOrThrow<{ slug: string; previous_slug: string | null }>(
        res,
      );
      setCurrentSlug(data.slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(anchorId: string) {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/anchors/${encodeURIComponent(anchorId)}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `${res.status} ${res.statusText}`);
      }
      setAnchors((prev) => prev.filter((a) => a.id !== anchorId));
      if (pendingGithub?.anchorId === anchorId) setPendingGithub(null);
      if (pendingTelegram?.anchorId === anchorId) setPendingTelegram(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const verified = anchors.filter((a) => a.verified_at);
  const pendingGithubRows = anchors.filter(
    (a) => !a.verified_at && a.type === "github",
  );
  const pendingTelegramRows = anchors.filter(
    (a) => !a.verified_at && a.type === "telegram",
  );

  function labelFor(type: string): string {
    if (type === "github") return "GitHub";
    if (type === "telegram") return "Telegram";
    if (type === "dns") return "DNS";
    return type;
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Verified anchors */}
      <section className="rounded-lg border bg-card p-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Verified anchors
        </div>
        {verified.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No anchors yet. Add one below to strengthen your verify page
            with an independent identity proof.
          </p>
        ) : (
          <ul className="space-y-2">
            {verified.map((a) => {
              const derived = previewSlug(a.value);
              const isActiveSlug =
                derived !== "" && derived === currentSlug;
              return (
                <li
                  key={a.id}
                  className="flex flex-col gap-2 rounded-md border bg-background/60 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div>
                      <span className="font-medium">
                        {labelFor(a.type)} ·{" "}
                        {/* GitHub stores the bare login; Telegram stores
                            the handle including the leading @. Render
                            consistently with one leading @ either way. */}
                        {a.value
                          ? a.value.startsWith("@")
                            ? a.value
                            : `@${a.value}`
                          : "—"}
                      </span>{" "}
                      <span className="text-xs text-muted-foreground">
                        via {a.method}
                      </span>
                    </div>
                    {derived && (
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {isActiveSlug ? (
                          <>
                            <span className="font-medium text-foreground">
                              Active public URL:
                            </span>{" "}
                            <code className="rounded bg-muted px-1">
                              /v/{currentSlug}
                            </code>
                          </>
                        ) : (
                          <>
                            Would claim{" "}
                            <code className="rounded bg-muted px-1">
                              /v/{derived}
                            </code>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {!isActiveSlug && derived && (
                      <button
                        type="button"
                        onClick={() => handleClaimSlug(a.id)}
                        disabled={busy}
                        className="rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-accent disabled:opacity-50"
                      >
                        {currentSlug
                          ? "Use this as public URL"
                          : "Claim public URL"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(a.id)}
                      disabled={busy}
                      className="text-xs text-destructive hover:underline disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* GitHub flow */}
      <section className="rounded-lg border bg-card p-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Add GitHub anchor
        </div>
        <p className="text-sm text-muted-foreground">
          Prove you control a GitHub account by posting a one-time
          challenge token in any public gist. We never ask for your
          GitHub token or password.
        </p>

        {!pendingGithub && (
          <button
            type="button"
            onClick={() => startFlow("github")}
            disabled={busy}
            className="mt-4 rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? "Working…" : "Start GitHub anchor"}
          </button>
        )}

        {pendingGithub && (
          <div className="mt-4 space-y-3">
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="font-medium">Step 1 — paste this in any public gist</div>
              <pre className="mt-2 overflow-x-auto rounded bg-background p-3 text-xs">
                <code>{pendingGithub.challengeToken}</code>
              </pre>
              <div className="mt-2 whitespace-pre-line text-xs text-muted-foreground">
                {pendingGithub.instructions}
              </div>
            </div>
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="font-medium">
                Step 2 — paste the gist URL here
              </div>
              <input
                type="url"
                placeholder="https://gist.github.com/your-username/abc123…"
                value={gistUrl}
                onChange={(e) => setGistUrl(e.target.value)}
                className="mt-2 w-full rounded-md border bg-background px-3 py-1.5 text-sm"
              />
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleVerifyGithub}
                  disabled={busy || !gistUrl.trim()}
                  className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
                >
                  {busy ? "Verifying…" : "Verify"}
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(pendingGithub.anchorId)}
                  disabled={busy}
                  className="text-xs text-muted-foreground hover:underline disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {pendingGithubRows.length > 0 && !pendingGithub && (
          <div className="mt-4 rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
            You have {pendingGithubRows.length} pending GitHub anchor
            {pendingGithubRows.length === 1 ? "" : "s"}. Click &ldquo;Start
            GitHub anchor&rdquo; to resume the flow (we&apos;ll reuse the
            existing token).
          </div>
        )}
      </section>

      {/* Telegram flow — Sprint UX-5.11 R2 / bug-r1-carlos-1.
          First-class because Carlos's JTBD ("anchor my bot's identity
          to the same @handle my subscribers already follow") doesn't
          require connecting a watcher. The challenge token goes in the
          bot's bio via @BotFather → /setdescription, or any user/channel
          bio. */}
      <section className="rounded-lg border bg-card p-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Add Telegram anchor
        </div>
        <p className="text-sm text-muted-foreground">
          Prove you control a Telegram bot, channel, or user account by
          pasting a short challenge token in its public bio. We read it
          once via the public t.me preview — no bot token needed, no
          watcher to connect first. You can remove the token from your
          bio right after verification.
        </p>

        {!pendingTelegram && (
          <button
            type="button"
            onClick={() => startFlow("telegram")}
            disabled={busy}
            className="mt-4 rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? "Working…" : "Start Telegram anchor"}
          </button>
        )}

        {pendingTelegram && (
          <div className="mt-4 space-y-3">
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="font-medium">
                Step 1 — paste this in the public bio
              </div>
              <pre className="mt-2 overflow-x-auto rounded bg-background p-3 text-xs">
                <code>{pendingTelegram.challengeToken}</code>
              </pre>
              <div className="mt-2 whitespace-pre-line text-xs text-muted-foreground">
                {pendingTelegram.instructions}
              </div>
            </div>
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="font-medium">
                Step 2 — enter the Telegram @username
              </div>
              <input
                type="text"
                placeholder="@my_signals_bot   (or my_signals_bot, or t.me/my_signals_bot)"
                value={telegramUsername}
                onChange={(e) => setTelegramUsername(e.target.value)}
                className="mt-2 w-full rounded-md border bg-background px-3 py-1.5 text-sm"
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
              />
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleVerifyTelegram}
                  disabled={busy || !telegramUsername.trim()}
                  className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
                >
                  {busy ? "Verifying…" : "Verify"}
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(pendingTelegram.anchorId)}
                  disabled={busy}
                  className="text-xs text-muted-foreground hover:underline disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {pendingTelegramRows.length > 0 && !pendingTelegram && (
          <div className="mt-4 rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
            You have {pendingTelegramRows.length} pending Telegram anchor
            {pendingTelegramRows.length === 1 ? "" : "s"}. Click
            &ldquo;Start Telegram anchor&rdquo; to resume — we&apos;ll
            reuse the existing token.
          </div>
        )}
      </section>
    </div>
  );
}
