"use client";

/**
 * IssueClaim — verification-proof generator.
 *
 * Sprint 6-A2A 6.1 introduced the flow as a B2B "issue a JWT for the
 * relying party to verify" tool. Sprint UX-5.11 R2 / R2.4d (2026-05-18)
 * reworks it around the bigger product story:
 *
 *   The reference word ("scope") is the PRIMARY field. When a visitor
 *   suspects they're talking to an impersonator, they ask the agent's
 *   owner for a fresh proof with a reference word THEY choose. The
 *   operator generates one here, copies the resulting verify URL
 *   (`/v/<slug>?proof=<JWT>`), and pastes it back. The visitor opens
 *   the URL, sees the reference word displayed prominently on the
 *   verify page, and confirms it matches what they asked for. A
 *   stolen / replayed link won't match, so it's the strong defense
 *   against link-squatting.
 *
 * D-PROD.18 reminder: never name κ-Proof / RS256 / JWKS in customer
 * copy. We say "verification proof" / "verification link".
 */
import { useState } from "react";
import { Copy, Check, ShieldCheck, X, ExternalLink } from "lucide-react";

const ISSUE_PROOF_TTLS = [
  { seconds: 300, label: "5 min" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 86400, label: "24 hours" },
] as const;

interface IssueProofResult {
  proof_id: string;
  agent_id: string;
  kappa_proof: string;
  issued_at: string;
  expires_at: string;
  scope: string | null;
  score: number | null;
}

interface Props {
  agentId: string;
  agentName: string;
  /** Sprint UX-5.11 R2 / R2.4d — used to build the verify URL we copy
   * out for the operator. Falls back to /verify/<agent_id> if no slug. */
  publicSlug?: string | null;
}

export function IssueClaim({ agentId, agentName, publicSlug }: Props) {
  const [open, setOpen] = useState(false);
  // Default TTL: 5 min. That matches the human-to-human flow
  // ("ask the operator to send me a fresh proof") much better than
  // the old 1h default, which read more like a B2B service token.
  const [ttlSeconds, setTtlSeconds] = useState<number>(300);
  const [reference, setReference] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<IssueProofResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  function reset() {
    setOpen(false);
    setResult(null);
    setError(null);
    setCopiedField(null);
    setReference("");
    setTtlSeconds(300);
  }

  function buildVerifyUrl(proofId: string): string {
    // Sprint UX-5.11 R2 / R2.7 (2026-05-18). Use the short ?p=<proof_id>
    // form (~70 chars total) instead of embedding the full JWT
    // (~700 chars). Both are accepted by the verify page; the short
    // one is what we generate for humans sharing in chat / bios.
    const path = publicSlug
      ? `/v/${encodeURIComponent(publicSlug)}`
      : `/verify/${encodeURIComponent(agentId)}`;
    const origin =
      typeof window !== "undefined" ? window.location.origin : "";
    return `${origin}${path}?p=${encodeURIComponent(proofId)}`;
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const trimmed = reference.trim();
      const res = await fetch(
        `/api/agents/${encodeURIComponent(agentId)}/issue-proof`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ttl_seconds: ttlSeconds,
            // The backend field is still `scope` (kept for backward
            // compat with the existing JWT claim shape). UI-side we
            // call it "reference word" because that's how a human
            // thinks about it.
            scope: trimmed.length > 0 ? trimmed : undefined,
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          body?.detail || `Request failed (HTTP ${res.status})`,
        );
      }
      const data: IssueProofResult = await res.json();
      setResult(data);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function copyTo(field: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      // Clipboard blocked — user can still select manually.
    }
  }

  const verifyUrl = result ? buildVerifyUrl(result.proof_id) : "";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300"
      >
        <ShieldCheck size={16} />
        Generate verification proof
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) reset();
          }}
        >
          <div className="w-full max-w-md rounded-lg border bg-card p-6 shadow-xl">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="text-lg font-semibold">
                  {result
                    ? "Your verification link is ready"
                    : "Generate a verification proof"}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {result
                    ? "Send this URL to the person who asked you to prove your identity. They open it and see the reference word."
                    : `For ${agentName}. Use this when someone asks you to prove this is your agent.`}
                </p>
              </div>
              <button
                onClick={reset}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Close"
              >
                <X size={18} />
              </button>
            </div>

            {!result && (
              <div className="space-y-4">
                {/* Reference word — now the PRIMARY field. Optional in
                    the API, but the whole point of the proof is that
                    the visitor's word is baked in. Without it the proof
                    is replayable. */}
                <div>
                  <label
                    htmlFor="claim-reference"
                    className="mb-2 block text-sm font-medium"
                  >
                    Reference word from the person verifying you
                  </label>
                  <input
                    id="claim-reference"
                    type="text"
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                    placeholder="e.g. cucumber-42 — anything they tell you"
                    maxLength={128}
                    autoComplete="off"
                    autoCapitalize="off"
                    autoCorrect="off"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                  />
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Ask the person who needs the proof to give you a
                    short word. We bake it into the link they receive
                    — they&apos;ll see it on the verify page and confirm
                    it&apos;s the same word. Without it the link can be
                    replayed.
                  </p>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium">
                    How long should it stay valid?
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {ISSUE_PROOF_TTLS.map((t) => (
                      <button
                        key={t.seconds}
                        onClick={() => setTtlSeconds(t.seconds)}
                        className={`rounded-md border px-3 py-2 text-sm transition ${
                          ttlSeconds === t.seconds
                            ? "border-primary bg-primary/10 font-medium text-primary"
                            : "border-input hover:bg-accent"
                        }`}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Shorter is safer. 5 min is enough for a chat
                    handoff.
                  </p>
                </div>

                {error && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                    {error}
                  </div>
                )}

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={reset}
                    className="rounded-md border px-4 py-2 text-sm hover:bg-accent"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSubmit}
                    disabled={submitting}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {submitting ? "Generating…" : "Generate proof"}
                  </button>
                </div>
              </div>
            )}

            {result && (
              <div className="space-y-4">
                {/* Primary output: the verify URL. This is what the
                    operator sends to the person verifying them. The raw
                    JWT is exposed only as an advanced-collapsible
                    section below for A2A integrators. */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Verification link (send this)
                    </span>
                    <button
                      onClick={() => copyTo("url", verifyUrl)}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                    >
                      {copiedField === "url" ? (
                        <>
                          <Check size={14} /> Copied
                        </>
                      ) : (
                        <>
                          <Copy size={14} /> Copy link
                        </>
                      )}
                    </button>
                  </div>
                  <pre className="max-h-32 overflow-auto rounded-md border bg-muted/50 p-3 text-[11px] font-mono leading-snug break-all whitespace-pre-wrap">
                    {verifyUrl}
                  </pre>
                  <a
                    href={verifyUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
                  >
                    <ExternalLink size={12} /> Preview what the recipient sees
                  </a>
                </div>

                <dl className="grid grid-cols-2 gap-2 text-xs">
                  {result.scope && (
                    <div className="col-span-2">
                      <dt className="text-muted-foreground">Reference</dt>
                      <dd className="font-mono text-sm font-semibold">
                        {result.scope}
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt className="text-muted-foreground">Issued</dt>
                    <dd className="font-medium">
                      {new Date(result.issued_at).toLocaleString()}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Expires</dt>
                    <dd className="font-medium">
                      {new Date(result.expires_at).toLocaleString()}
                    </dd>
                  </div>
                </dl>

                {!result.scope && (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300">
                    <strong className="font-semibold">No reference word.</strong>{" "}
                    The link is still valid, but anyone with it can
                    show the verify page — there&apos;s nothing binding
                    it to a specific person. For human verification we
                    strongly recommend including a reference.
                  </div>
                )}

                {/* Raw token — for A2A / programmatic integrators who
                    want to verify server-side against /v1/verify-proof
                    instead of opening the URL. */}
                <details className="rounded-md border bg-muted/30 p-3 text-xs">
                  <summary className="cursor-pointer font-medium text-foreground">
                    Advanced: raw proof token (for A2A integrations)
                  </summary>
                  <div className="mt-2 space-y-2">
                    <p className="text-muted-foreground">
                      Programmatic relying parties can POST this token to{" "}
                      <code className="font-mono">
                        https://api.metalins.ai/v1/verify-proof
                      </code>
                      . The endpoint is public and returns yes/no in
                      milliseconds.
                    </p>
                    <div className="flex items-center gap-2">
                      <pre className="max-h-24 flex-1 overflow-auto rounded border bg-background p-2 font-mono text-[10px] leading-snug break-all whitespace-pre-wrap">
                        {result.kappa_proof}
                      </pre>
                      <button
                        onClick={() => copyTo("jwt", result.kappa_proof)}
                        className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
                      >
                        {copiedField === "jwt" ? (
                          <>
                            <Check size={12} /> Copied
                          </>
                        ) : (
                          <>
                            <Copy size={12} /> Copy
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </details>

                <div className="flex justify-end">
                  <button
                    onClick={reset}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
