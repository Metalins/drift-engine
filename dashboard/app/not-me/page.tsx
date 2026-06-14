"use client";

/**
 * /not-me — "this wasn't me" report for an unsolicited magic-link email.
 *
 * Phase-2 anti-abuse (Jose, 2026-05-21). The magic-link email links
 * here with ?e=<address>. The visitor confirms with a Cloudflare
 * Turnstile human-check; on success we POST a report to the API,
 * which flags the address. A flagged address is gated at login
 * (routed to support) until support clears it.
 *
 * Turnstile is the anti-script gate — without a human solve no flag is
 * recorded, so the report can't be weaponized in bulk. If Turnstile
 * isn't configured yet the page degrades to a "contact support" note.
 */
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

const API_BASE =
  process.env.NEXT_PUBLIC_METALINS_API_URL ?? "https://api.metalins.ai";
const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
const TURNSTILE_SCRIPT =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

declare global {
  interface Window {
    turnstile?: {
      render: (
        el: HTMLElement,
        opts: {
          sitekey: string;
          callback: (token: string) => void;
          "error-callback"?: () => void;
          "expired-callback"?: () => void;
        },
      ) => string;
    };
  }
}

export default function NotMePage() {
  return (
    <Suspense fallback={null}>
      <NotMeInner />
    </Suspense>
  );
}

function NotMeInner() {
  const email = (useSearchParams().get("e") ?? "").trim();
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "submitting" }
    | { kind: "done" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });
  const widgetRef = useRef<HTMLDivElement>(null);
  const renderedRef = useRef(false);

  // Load + render the Turnstile widget once.
  useEffect(() => {
    const siteKey = TURNSTILE_SITE_KEY;
    if (!siteKey || !email) return;
    function render() {
      if (renderedRef.current || !widgetRef.current || !window.turnstile)
        return;
      renderedRef.current = true;
      window.turnstile.render(widgetRef.current, {
        sitekey: siteKey as string,
        callback: (t) => setToken(t),
        "expired-callback": () => setToken(null),
        "error-callback": () => setToken(null),
      });
    }
    if (window.turnstile) {
      render();
      return;
    }
    let script = document.querySelector<HTMLScriptElement>(
      `script[src="${TURNSTILE_SCRIPT}"]`,
    );
    if (!script) {
      script = document.createElement("script");
      script.src = TURNSTILE_SCRIPT;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", render);
    return () => script?.removeEventListener("load", render);
  }, [email]);

  const submit = useCallback(async () => {
    if (!token) return;
    setStatus({ kind: "submitting" });
    try {
      const res = await fetch(`${API_BASE}/v1/auth-email/report-unsolicited`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, turnstile_token: token }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setStatus({ kind: "done" });
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : "Something went wrong.",
      });
    }
  }, [token, email]);

  return (
    <main className="mx-auto max-w-md py-8">
      <div className="rounded-lg border bg-card p-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          Didn&apos;t request this?
        </h1>

        {!email ? (
          <p className="mt-3 text-sm text-muted-foreground">
            This page needs the email address from the link in your
            message. If you keep receiving Metalins sign-in emails you
            didn&apos;t ask for, contact{" "}
            <a
              href="mailto:support@metalins.com"
              className="font-medium text-foreground underline"
            >
              support@metalins.com
            </a>
            .
          </p>
        ) : status.kind === "done" ? (
          <p className="mt-3 text-sm text-muted-foreground">
            Thanks — we&apos;ve noted that{" "}
            <span className="font-medium text-foreground">{email}</span>{" "}
            didn&apos;t request a Metalins sign-in. We&apos;ll stop sending
            sign-in links to it. If you ever do want to use Metalins with
            this address, contact{" "}
            <a
              href="mailto:support@metalins.com"
              className="font-medium text-foreground underline"
            >
              support@metalins.com
            </a>
            .
          </p>
        ) : (
          <>
            <p className="mt-3 text-sm text-muted-foreground">
              Someone asked Metalins to send a sign-in link to{" "}
              <span className="font-medium text-foreground">{email}</span>.
              If that wasn&apos;t you, confirm below and we&apos;ll stop
              sending sign-in links to this address. No account is created
              unless a link is actually used.
            </p>

            {TURNSTILE_SITE_KEY ? (
              <>
                <div ref={widgetRef} className="mt-5" />
                <button
                  type="button"
                  onClick={submit}
                  disabled={!token || status.kind === "submitting"}
                  className="mt-4 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {status.kind === "submitting"
                    ? "Submitting…"
                    : "I didn't request this"}
                </button>
                {status.kind === "error" && (
                  <p className="mt-2 text-sm text-destructive">
                    {status.message}
                  </p>
                )}
              </>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">
                To report this, contact{" "}
                <a
                  href="mailto:support@metalins.com"
                  className="font-medium text-foreground underline"
                >
                  support@metalins.com
                </a>
                .
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
}
