"use client";

/**
 * ShareVerification — Sprint UX-5.5c + Sprint UX-5.7a (#634) + Sprint
 * UX-5.10-5 (#663) + Sprint UX-5.11 / Carlos round 0 (#750).
 *
 * Prominent card shown in the agent-detail Calma + Baselining states.
 * The card is the Carlos / Sofía JTBD as a first-class UI element:
 *
 *   1. A public verification URL anchored to this agent's slug.
 *      One-click copy. "Preview" link to see what visitors see.
 *   2. Quick-share buttons that pre-populate Telegram / X / WhatsApp
 *      share intents with the verify link + a short message. Carlos
 *      flagged that if sharing took more than one tap he'd forget
 *      about it within 48h (Round 0 v1).
 *   3. An embeddable badge — SVG served from
 *      `/v1/public/badge/<slug>.svg`. Markdown and HTML snippets, each
 *      with their own copy button. Live preview of the badge image.
 *
 * URL preference order is slug → agent_id (legacy fallback for agents
 * without a slug yet). The badge is gated on slug presence because the
 * badge endpoint resolves by slug — without one, we just hide the
 * embed section rather than render a broken badge.
 *
 * Variant `compact` is used in the baselining state where we want the
 * link surfaced but de-emphasized (smaller header, no badge embed).
 */
import { useState } from "react";
import { Check, Copy, ExternalLink, Share2 } from "lucide-react";

interface Props {
  agentId: string;
  agentName?: string;
  publicSlug?: string | null;
  /** When true, render a slim variant suitable for baselining state. */
  compact?: boolean;
  /**
   * Sprint UX-5.11 / bug-sofia-1 (2026-05-17). Vendor Day-1 case:
   * agent is freshly registered, event_count === 0, crypto state is
   * still 'unverified'. We surface the share UI anyway with copy that
   * frames the link as 'registered with Metalins, awaiting first
   * signed activity' instead of overclaiming 'verified'. The badge
   * embed still renders — its image reflects the registered-but-empty
   * state honestly (the badge endpoint renders the current state).
   *
   * - "active"      — agent has logged ≥ 1 event. Default copy.
   * - "registered"  — event_count === 0. Reframe copy + badge still shown.
   */
  daystate?: "active" | "registered";
}

const API_URL = (
  process.env.NEXT_PUBLIC_METALINS_API_URL || "https://api.metalins.ai"
).replace(/\/$/, "");

export function ShareVerification({
  agentId,
  // agentName is still accepted by callers but no longer used in the
  // body since gh-124 removed the pre-filled social share message.
  publicSlug,
  compact = false,
  daystate = "active",
}: Props) {
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const path = publicSlug
    ? `/v/${encodeURIComponent(publicSlug)}`
    : `/verify/${encodeURIComponent(agentId)}`;
  const url =
    typeof window !== "undefined"
      ? `${window.location.origin}${path}`
      : path;
  // Sprint UX-5.11 R2 / R2.3d (2026-05-18). Under "Full C" policy
  // agents are slugless at register time — they live at /verify/<id>
  // until the customer verifies an anchor and claims a derived
  // /v/<slug>. The URL above still works, but we surface a small CTA
  // so the creator knows there's a clean-URL upgrade available.
  const hasCleanSlug = Boolean(publicSlug);

  // Badge embed snippets — only meaningful when we have a slug. Without
  // a slug the badge endpoint can't resolve; we hide the section
  // entirely so the user doesn't paste a snippet that 404s.
  const badgeSrc = publicSlug
    ? `${API_URL}/v1/public/badge/${encodeURIComponent(publicSlug)}.svg`
    : null;
  const markdownSnippet = badgeSrc
    ? `[![Verified by Metalins](${badgeSrc})](${url})`
    : null;
  const htmlSnippet = badgeSrc
    ? `<a href="${url}"><img src="${badgeSrc}" alt="Verified by Metalins" /></a>`
    : null;

  async function copyTo(field: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      // Clipboard blocked — user can still select manually.
    }
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="flex items-start gap-3">
        <span
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          aria-hidden="true"
        >
          <Share2 size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-medium">
            {daystate === "registered"
              ? "Share verification (Day-1 link)"
              : "Share verification"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {daystate === "registered" ? (
              <>
                Your link is live the moment you register. Anyone with it
                sees this agent&apos;s current state — including
                &ldquo;registered with Metalins, awaiting first signed
                activity&rdquo; until traffic flows. As soon as your
                agent logs its first event, the page upgrades to
                cryptographically verified — no edit on your end.
              </>
            ) : (
              <>
                Anyone with this link can confirm your agent is the real
                one &mdash; in one click, no signup. Share this link so
                anyone can verify your agent without signing up.
              </>
            )}
          </p>

          {!hasCleanSlug && (
            <div className="mt-3 rounded-md border border-dashed bg-muted/30 p-3 text-xs">
              <div className="font-medium text-foreground">
                Want a cleaner URL like{" "}
                <code className="rounded bg-background px-1">
                  /v/your-handle
                </code>
                ?
              </div>
              <p className="mt-1 text-muted-foreground">
                Verify a Telegram bot, GitHub account, or DNS domain you
                control — you can claim the matching slug in one click.
                The URL above keeps working either way.
              </p>
              <a
                href={`/agents/${encodeURIComponent(agentId)}/anchors`}
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-foreground hover:underline"
              >
                Verify an anchor →
              </a>
            </div>
          )}

          <div className="mt-3 flex gap-2">
            <input
              type="text"
              value={url}
              readOnly
              className="min-w-0 flex-1 truncate rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
              onFocus={(e) => e.currentTarget.select()}
            />
            <button
              onClick={() => copyTo("url", url)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {copiedField === "url" ? (
                <>
                  <Check size={14} /> Copied
                </>
              ) : (
                <>
                  <Copy size={14} /> Copy
                </>
              )}
            </button>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              <ExternalLink size={12} aria-hidden="true" />
              Preview how this looks to a visitor
            </a>
            {/* Sprint UX-5.11 R2: this is the trust-distribution hint.
                Without an anchor visitors can only trust Metalins; with
                one (Telegram @, GitHub, DNS) they cross-check on a
                platform they already know. Marked optional explicitly. */}
            <a
              href={`/agents/${encodeURIComponent(agentId)}/anchors`}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground hover:underline"
              title="An anchor links this agent to a public identity you already control (Telegram, GitHub, or DNS). Visitors cross-check it themselves — optional but recommended for share."
            >
              + Add external anchor (optional, helps visitors trust)
            </a>
          </div>

          {/* gh-124 — Social quick-share buttons (Telegram / X /
              WhatsApp) removed for self-hosted. Verify links point at
              the operator's own domain (or localhost); broadcasting them
              to social networks isn't relevant for a B2B self-hosted
              product. The URL + Copy above covers sharing. */}

          {/* Embed badge — Sprint UX-5.10-5. Hidden in compact mode
              (baselining state) because we want the URL + share to
              dominate; embed surfaces fully in Calma. */}
          {!compact && badgeSrc && markdownSnippet && htmlSnippet && (
            <div className="mt-5 border-t pt-4">
              <div className="flex items-center gap-3">
                <div className="text-sm font-medium">Embed a badge</div>
                {/* Live preview of the actual badge — eslint-disable
                    next/no-img-element because external SVG by design. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={badgeSrc}
                  alt="Verified by Metalins"
                  height={20}
                  className="h-5"
                />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Drop this in your README, listing, or docs. The badge
                always reflects this agent&apos;s current state.
              </p>

              <SnippetField
                label="Markdown"
                value={markdownSnippet}
                copied={copiedField === "md"}
                onCopy={() => copyTo("md", markdownSnippet)}
              />
              <SnippetField
                label="HTML"
                value={htmlSnippet}
                copied={copiedField === "html"}
                onCopy={() => copyTo("html", htmlSnippet)}
              />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function SnippetField({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          readOnly
          className="min-w-0 flex-1 truncate rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
          onFocus={(e) => e.currentTarget.select()}
        />
        <button
          onClick={onCopy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-medium hover:bg-accent"
        >
          {copied ? (
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
  );
}
