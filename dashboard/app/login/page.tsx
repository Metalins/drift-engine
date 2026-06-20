/**
 * /login — self-hosted email + password sign-in (gh-119).
 *
 * Self-hosting pivot: there is no Supabase and no magic-link. The Drift Engine
 * server owns auth. This form posts to the local `/api/auth/login` route
 * handler, which calls the server's `POST /auth/login`, gets a session JWT
 * back and stores it in the httpOnly `ml_session` cookie. On success we push
 * the user to wherever they were heading (`redirectTo`), or to the dashboard.
 *
 * Client Component. Reads `redirectTo` from the query string (set by
 * middleware when bouncing an unauthenticated request).
 */
"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LoginPage() {
  // Next 15+ requires components reading useSearchParams() to be wrapped in
  // a Suspense boundary so they can opt into client-side rendering.
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}

function LoginPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const redirectTo = searchParams.get("redirectTo") ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "submitting" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!email || !password) return;
    setStatus({ kind: "submitting" });
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setStatus({
          kind: "error",
          message: body.detail ?? "Incorrect email or password.",
        });
        return;
      }
      const body = (await res.json()) as { must_change_password?: boolean };
      // Force-change flow: a freshly bootstrapped admin still has the default
      // password — send them to settings to set a real one before anything else.
      if (body.must_change_password) {
        router.replace("/settings?changePassword=1");
      } else {
        router.replace(redirectTo);
      }
      router.refresh();
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }

  return (
    <main className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-md flex-col justify-center px-4 py-8">
      <div className="rounded-lg border bg-card p-8 shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight">
          Sign in to Drift Engine
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sign in with your administrator email and password.
        </p>

        {/* Self-hosted context: this dashboard ships with the open-source
            Drift Engine server. The default admin credentials are printed in
            the server logs on first boot — see the getting-started guide. */}
        <div className="mt-4 rounded-md border-l-4 border-emerald-500 bg-emerald-500/5 p-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">
            Self-hosted Drift Engine instance.
          </p>
          <p className="mt-1">
            First boot creates an admin account and prints its default
            password to the server logs. Sign in, then change it from{" "}
            <span className="font-medium">Settings → Password</span>. See the{" "}
            <a
              href="https://github.com/Metalins/drift-engine"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium underline hover:text-foreground"
            >
              repo on GitHub
            </a>
            .
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-6 space-y-3">
          <label className="block text-sm font-medium">
            Email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={status.kind === "submitting"}
              placeholder="admin@example.com"
              className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            />
          </label>
          <label className="block text-sm font-medium">
            Password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={status.kind === "submitting"}
              className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
            />
          </label>
          <button
            type="submit"
            disabled={status.kind === "submitting" || !email || !password}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {status.kind === "submitting" ? "Signing in…" : "Sign in"}
          </button>
          {status.kind === "error" && (
            <p className="text-sm text-destructive">{status.message}</p>
          )}
        </form>

        <p className="mt-6 text-xs text-muted-foreground">
          By signing in you agree to our{" "}
          <a href="/terms" className="underline hover:text-foreground">
            Terms &amp; Conditions
          </a>{" "}
          and{" "}
          <a href="/privacy" className="underline hover:text-foreground">
            Privacy Policy
          </a>
          .
        </p>
      </div>
    </main>
  );
}
