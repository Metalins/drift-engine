"use client";

/**
 * DeleteAccount — the danger-zone section of /settings.
 *
 * Free tier (Jose, 2026-05-22): account deletion is immediate. It
 * wipes every agent and all of its data, the account-level rows, and
 * the account record itself — we keep nothing afterwards but one audit
 * row (email + when + reason). The reason is mandatory; deletion also
 * requires typing the account email to confirm.
 */
import { useState } from "react";

export function DeleteAccount({ email }: { email: string }) {
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "deleting" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  const reasonOk = reason.trim().length > 0;
  const confirmOk =
    confirm.trim().toLowerCase() === email.trim().toLowerCase();
  const canDelete = reasonOk && confirmOk && status.kind !== "deleting";

  async function handleDelete() {
    if (!canDelete) return;
    setStatus({ kind: "deleting" });
    try {
      const res = await fetch("/api/me/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      // The account and its session are gone server-side. Drop the local
      // session cookie too, then leave the app.
      try {
        await fetch("/auth/signout", { method: "POST" });
      } catch {
        // already gone server-side — nothing to clean up
      }
      window.location.href = "/";
    } catch (e) {
      setStatus({
        kind: "error",
        message:
          e instanceof Error ? e.message : "Could not delete the account.",
      });
    }
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-medium text-destructive">
          Delete account
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Permanently delete your Drift Engine account. This is immediate
          and cannot be undone &mdash; every agent and all of its data
          (events, event logs, identity history, API keys) is erased.
          We keep nothing afterwards, only an audit record of the
          deletion.
        </p>
      </div>
      <div className="space-y-3 rounded-lg border border-destructive/40 bg-destructive/[0.04] p-5">
        <label className="block">
          <span className="text-sm font-medium">
            Why are you deleting your account?{" "}
            <span className="text-destructive">*</span>
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="A short reason — required."
            disabled={status.kind === "deleting"}
            className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">
            Type{" "}
            <span className="font-mono text-foreground">{email}</span> to
            confirm
          </span>
          <input
            type="text"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="off"
            disabled={status.kind === "deleting"}
            className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
          />
        </label>
        <button
          type="button"
          onClick={handleDelete}
          disabled={!canDelete}
          className="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
        >
          {status.kind === "deleting"
            ? "Deleting…"
            : "Delete my account permanently"}
        </button>
        {status.kind === "error" && (
          <p className="text-sm text-destructive">{status.message}</p>
        )}
      </div>
    </section>
  );
}
