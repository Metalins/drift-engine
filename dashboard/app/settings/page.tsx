/**
 * /settings — account settings page.
 *
 * Sprint UX-5.11-pwd. Currently a single section: change password. Lives
 * under a real route (not a modal) so it can be linked from anywhere and
 * shows up in browser history.
 *
 * Server Component shell — guards the route via middleware (already added
 * /settings to PRIVATE_PREFIXES). The actual form is the Client Component
 * `PasswordForm` so it can call `supabase.auth.updateUser`.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { KeyRound, ArrowRight } from "lucide-react";
import { getCurrentUser } from "@/lib/auth/server";
import { PasswordForm } from "./PasswordForm";
import { EmailPreferencesForm } from "./EmailPreferencesForm";
import { DeleteAccount } from "./DeleteAccount";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Settings",
};

export default async function SettingsPage() {
  // Defense-in-depth: middleware already enforces auth, but if it ever
  // breaks we want to fail closed, not render an empty form that quietly
  // does nothing.
  const user = await getCurrentUser();
  if (!user) redirect("/login?redirectTo=/settings");

  return (
    <main className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Account-level configuration. Signed in as{" "}
          <span className="font-medium text-foreground">{user.email}</span>.
        </p>
      </div>

      {/* Sprint UX-5.15.Z (2026-05-19) — API keys promoted from the
          top nav to a section inside Settings (per Jose's nav
          cleanup). The full keys table still lives at /keys; this
          card surfaces it as an account-level setting and is the
          new discoverability path. */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium">API keys</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Keys authenticate your agents and SDK calls against
            Metalins. Mint new keys, rotate, or revoke from the
            keys page.
          </p>
        </div>
        <Link
          href="/keys"
          className="group flex items-center justify-between rounded-lg border bg-card p-4 transition-colors hover:border-foreground/20 hover:bg-accent/40"
        >
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <KeyRound size={18} aria-hidden />
            </div>
            <div>
              <div className="text-sm font-medium">Manage API keys</div>
              <div className="text-xs text-muted-foreground">
                View, mint, and revoke keys for this account.
              </div>
            </div>
          </div>
          <ArrowRight
            size={16}
            className="text-muted-foreground transition-transform group-hover:translate-x-0.5"
            aria-hidden
          />
        </Link>
      </section>

      {/* Sprint UX-5.13.E.5 (#811) — email preferences. Andrea's P0
          (bug-r1-andrea-1). The form is calm by default and saves on
          every toggle change so users never wonder if the change took. */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium">Email alerts</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            We email you when an agent&apos;s verification state changes.
            Set the address and pick which events deserve a wake-up.
          </p>
        </div>
        <EmailPreferencesForm authEmail={user.email ?? ""} />
      </section>

      {/* Password sits last (Jose, 2026-05-21): it's the set-once,
          least-touched setting. API keys and email alerts are the
          configuration users actually come back to. */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium">Password</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Sign in to Metalins with email + password as an alternative to
            magic-link. New accounts are created via magic-link only — set
            your first password here once you&apos;re signed in.
          </p>
        </div>
        <PasswordForm />
      </section>

      <DeleteAccount email={user.email ?? ""} />
    </main>
  );
}
