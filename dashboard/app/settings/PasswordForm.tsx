/**
 * Password change form — Client Component (gh-119 self-hosted auth).
 *
 * Lets a logged-in user change their password. The Drift Engine server
 * requires the CURRENT password (POST /auth/change-password), so unlike the
 * old Supabase flow we ask for it here. This is also the forced-change flow
 * for a freshly bootstrapped admin still on the default password.
 *
 * Min length is 8 (mirrors the server's MIN_PASSWORD_LEN). We check it
 * client-side so the user sees inline feedback before the round-trip.
 */
"use client";

import { useState } from "react";

type Status =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success" }
  | { kind: "error"; message: string };

const MIN_LENGTH = 8;

export function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [pwd, setPwd] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const tooShort = pwd.length > 0 && pwd.length < MIN_LENGTH;
  const mismatched = confirm.length > 0 && pwd !== confirm;
  const canSubmit =
    current.length > 0 &&
    pwd.length >= MIN_LENGTH &&
    pwd === confirm &&
    status.kind !== "submitting";

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus({ kind: "submitting" });
    try {
      const res = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: current,
          new_password: pwd,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setStatus({
          kind: "error",
          message: body.detail ?? `HTTP ${res.status}`,
        });
        return;
      }
      setCurrent("");
      setPwd("");
      setConfirm("");
      setStatus({ kind: "success" });
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-lg border bg-card p-6"
    >
      <label className="block text-sm font-medium">
        Current password
        <input
          type={show ? "text" : "password"}
          required
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          disabled={status.kind === "submitting"}
          className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
        />
      </label>

      <label className="block text-sm font-medium">
        New password
        <input
          type={show ? "text" : "password"}
          required
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          value={pwd}
          onChange={(e) => setPwd(e.target.value)}
          disabled={status.kind === "submitting"}
          className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
        />
        {tooShort && (
          <span className="mt-1 block text-xs text-destructive">
            Must be at least {MIN_LENGTH} characters.
          </span>
        )}
      </label>

      <label className="block text-sm font-medium">
        Confirm new password
        <input
          type={show ? "text" : "password"}
          required
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          disabled={status.kind === "submitting"}
          className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
        />
        {mismatched && (
          <span className="mt-1 block text-xs text-destructive">
            Passwords don&apos;t match.
          </span>
        )}
      </label>

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={show}
          onChange={(e) => setShow(e.target.checked)}
          className="rounded border-input"
        />
        Show passwords
      </label>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {status.kind === "submitting" ? "Saving…" : "Save password"}
        </button>
        {status.kind === "success" && (
          <span className="text-sm text-emerald-600">
            Password updated.
          </span>
        )}
        {status.kind === "error" && (
          <span className="text-sm text-destructive">{status.message}</span>
        )}
      </div>
    </form>
  );
}
