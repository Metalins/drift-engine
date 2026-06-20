"use client";

/**
 * EmailPreferencesForm — Sprint UX-5.13.E.5 (2026-05-18).
 *
 * Reads + writes /v1/me/email-preferences via the dashboard proxy. The
 * form is intentionally calm:
 *   - Email field with a placeholder showing the auth email as the
 *     fallback ("we'll send to <auth.email> by default").
 *   - Master "alerts on/off" toggle at the top — turning it off
 *     greys the per-event toggles (still visible so the user knows
 *     what's in there, but clearly inactive).
 *   - Per-event toggle: verification state changes. The drift and
 *     weekly-digest toggles are hidden until their backends ship
 *     (2026-05-21) — they were no-ops; the EmailPreferences fields
 *     stay so the API contract is intact.
 *
 * State machine: idle → loading → ready → saving → saved | error.
 * We always re-fetch after save so what's on screen matches what the
 * server actually persisted (which may diff from what we POSTed if
 * validation cleaned up the input).
 */
import { useEffect, useState } from "react";

interface EmailPreferences {
  alert_email: string | null;
  effective_email: string;
  alerts_enabled: boolean;
  threshold_crossed_enabled: boolean;
  drift_detected_enabled: boolean;
  weekly_digest_enabled: boolean;
  is_default: boolean;
}

type Status =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

export function EmailPreferencesForm({
  authEmail,
}: {
  authEmail: string;
}) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  const [prefs, setPrefs] = useState<EmailPreferences | null>(null);
  const [dirtyEmail, setDirtyEmail] = useState<string>("");

  // ----- initial fetch -----
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/api/me/email-preferences", {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as EmailPreferences;
        if (cancelled) return;
        setPrefs(body);
        setDirtyEmail(body.alert_email ?? "");
        setStatus({ kind: "ready" });
      } catch (e) {
        if (cancelled) return;
        setStatus({
          kind: "error",
          message:
            e instanceof Error
              ? e.message
              : "Could not load email preferences.",
        });
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function patch(partial: Partial<EmailPreferences>): Promise<void> {
    setStatus({ kind: "saving" });
    try {
      const res = await fetch("/api/me/email-preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(partial),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const refreshed = (await res.json()) as EmailPreferences;
      setPrefs(refreshed);
      setDirtyEmail(refreshed.alert_email ?? "");
      setStatus({ kind: "saved" });
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : "Save failed.",
      });
    }
  }

  if (status.kind === "loading" || prefs === null) {
    return (
      <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
        Loading email preferences…
      </div>
    );
  }

  const masterOff = !prefs.alerts_enabled;
  const emailDirty = dirtyEmail !== (prefs.alert_email ?? "");

  return (
    <div className="space-y-5 rounded-lg border bg-card p-6">
      {/* Master switch */}
      <label className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={prefs.alerts_enabled}
          onChange={(e) =>
            patch({ alerts_enabled: e.target.checked })
          }
          disabled={status.kind === "saving"}
          className="mt-1 h-4 w-4 accent-primary"
        />
        <span className="min-w-0">
          <span className="block text-sm font-medium">Email alerts</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            Master switch for outbound emails. Off = we never email you
            (your dashboard and webhooks still work).
          </span>
        </span>
      </label>

      {/* Recipient */}
      <div className={masterOff ? "opacity-50" : ""}>
        <label className="block">
          <span className="text-sm font-medium">Where to send alerts</span>
          <input
            type="email"
            value={dirtyEmail}
            onChange={(e) => setDirtyEmail(e.target.value)}
            placeholder={authEmail}
            disabled={masterOff || status.kind === "saving"}
            className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed"
          />
          <span className="mt-1 block text-xs text-muted-foreground">
            {prefs.alert_email
              ? `Alerts go to ${prefs.alert_email}.`
              : `Empty = use your account email (${authEmail}).`}
          </span>
        </label>
        {emailDirty && (
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() =>
                patch({ alert_email: dirtyEmail })
              }
              disabled={masterOff || status.kind === "saving"}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              {status.kind === "saving" ? "Saving…" : "Save email"}
            </button>
            <button
              type="button"
              onClick={() => setDirtyEmail(prefs.alert_email ?? "")}
              disabled={status.kind === "saving"}
              className="rounded-md border px-3 py-1.5 text-xs hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Per-event toggles */}
      <fieldset
        className={masterOff ? "space-y-3 opacity-50" : "space-y-3"}
        disabled={masterOff}
      >
        <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          What to alert me about
        </legend>

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={prefs.threshold_crossed_enabled}
            onChange={(e) =>
              patch({ threshold_crossed_enabled: e.target.checked })
            }
            disabled={masterOff || status.kind === "saving"}
            className="mt-1 h-4 w-4 accent-primary"
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium">
              Verification state changes
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              We email you when an agent moves into &quot;needs attention&quot;
              or &quot;unusual activity&quot;.
            </span>
          </span>
        </label>

        {/* "Behavioral drift signals" and "Weekly digest" toggles are
            hidden until their backends ship (Jose, 2026-05-21) — they
            were no-ops and showed the user dead switches. The
            EmailPreferences fields stay so the API contract is intact;
            re-add the toggles here when the features land. */}
      </fieldset>

      {/* Status line */}
      <div className="text-xs text-muted-foreground">
        {status.kind === "saving" && "Saving…"}
        {status.kind === "saved" && (
          <span className="text-emerald-600 dark:text-emerald-400">
            ✓ Saved.
          </span>
        )}
        {status.kind === "error" && (
          <span className="text-destructive">{status.message}</span>
        )}
        {status.kind === "ready" && prefs.is_default && (
          <>Using defaults (no preferences saved yet).</>
        )}
      </div>
    </div>
  );
}
