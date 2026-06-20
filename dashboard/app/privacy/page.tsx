/**
 * /privacy — Privacy Policy. Public, indexable.
 *
 * Jose, 2026-05-21. Plain-language draft, written to be HONEST about
 * the product's core promise: Metalins works from hashes and never
 * sees prompts, responses, or end-user content.
 *
 * This is a starting draft, not lawyer-reviewed. Two things to verify
 * before launch: the sub-processor list in §6 (confirm it matches the
 * infrastructure actually in use) and the data-rights wording in §9
 * against the regimes Metalins markets to (GDPR, etc.).
 *
 * Section bodies live in a data array so the prose stays plain JS
 * strings (no JSX entity escaping needed).
 */
import Link from "next/link";

export const metadata = {
  title: "Privacy Policy — Metalins",
  description:
    "What Metalins collects, what it deliberately never sees, and how your data is handled. Metalins works from hashes plus low-resolution structural signals — never your prompts, outputs, tool arguments, or content.",
  alternates: { canonical: "/privacy" },
};

const LAST_UPDATED = "21 May 2026";

interface Section {
  heading: string;
  body: string[];
  bullets?: string[];
}

const SECTIONS: Section[] = [
  {
    heading: "1. Our approach",
    body: [
      "Metalins (“Metalins”, “we”, “us”) is built to verify your AI agents without seeing what they do. This policy explains what we collect, what we deliberately don’t, and how we handle it.",
    ],
  },
  {
    heading: "2. What we never see",
    body: [
      "We never receive your agents’ prompts, their responses, their tool arguments, your model weights, or your users’ data. Every event is hashed on your side before it reaches us. We store only those short, irreversible hashes — enough to verify identity, never enough to reconstruct what your agent said or did.",
    ],
  },
  {
    heading: "3. Structural signals we do receive",
    body: [
      "To detect behavioral drift, impersonation, and prompt injection, the SDK also computes a small set of low-resolution structural signals about each turn — in your process, before hashing — and sends them alongside the hashes. These are lengths, format flags (did the output contain a code block, a list?), sentence counts, the names of tools your agent called (never their arguments), latency, an error class, and a salted, irreversible fingerprint of the output’s vocabulary. They are designed to be too coarse to reconstruct content, and they are what let us monitor an agent’s behavior without ever reading it. This is on by default; you can turn it off (compute_behavioral=False) and identity verification still works on the hashes alone.",
    ],
  },
  {
    heading: "4. What we collect",
    body: ["To provide the service, we collect:"],
    bullets: [
      "Your account email — used for magic-link sign-in and account-related messages.",
      "Details you give us about your agents — names, the integration you chose, and similar settings.",
      "API keys you create to connect your agents.",
      "The hashes and signatures your agents send as they run.",
      "The low-resolution structural signals described in §3 (lengths, format flags, counts, tool names, latency, and a salted vocabulary fingerprint) — never the underlying content.",
      "Basic technical data such as IP address and timestamps, kept to operate and secure the service.",
    ],
  },
  {
    heading: "5. How we use it",
    body: [
      "We use this information only to provide and secure Metalins: to verify your agents, run your account, protect against abuse, and contact you about your account or the alerts you asked for. We don’t sell your data, and we don’t use it for advertising.",
    ],
  },
  {
    heading: "6. Service providers",
    body: [
      "We rely on a small set of third-party infrastructure providers to run Metalins — for hosting, database, and email delivery (currently Supabase, Cloudflare, Google Cloud, and Resend). They process data only to provide those services to us, under their own security and privacy commitments.",
    ],
  },
  {
    heading: "7. Cookies",
    body: [
      "We use only essential cookies — they keep you signed in. We don’t use advertising or third-party tracking cookies.",
    ],
  },
  {
    heading: "8. Keeping and deleting data",
    body: [
      "You can delete an agent at any time from its settings; this permanently removes that agent and its data, including its events and identity history. Deleting your account removes your account data. We keep data only as long as needed to provide the service or as required by law.",
    ],
  },
  {
    heading: "9. Your rights",
    body: [
      "You can ask to access, correct, export, or delete your personal data. Email support@metalins.com and we’ll help. Depending on where you live, you may have additional rights under local data-protection law.",
    ],
  },
  {
    heading: "10. Children",
    body: [
      "Metalins is not intended for children, and we don’t knowingly collect data from them.",
    ],
  },
  {
    heading: "11. Changes and contact",
    body: [
      "We may update this policy; the “last updated” date above reflects the latest version. Questions about your privacy: support@metalins.com.",
    ],
  },
];

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-8 py-4">
      <header className="space-y-2 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Legal
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Privacy Policy
        </h1>
        <p className="text-sm text-muted-foreground">
          Last updated {LAST_UPDATED}
        </p>
      </header>

      {SECTIONS.map((s) => (
        <section key={s.heading} className="space-y-2">
          <h2 className="text-lg font-semibold tracking-tight">
            {s.heading}
          </h2>
          {s.body.map((p, i) => (
            <p
              key={i}
              className="text-sm leading-relaxed text-muted-foreground"
            >
              {p}
            </p>
          ))}
          {s.bullets && (
            <ul className="ml-1 space-y-1.5 text-sm leading-relaxed text-muted-foreground">
              {s.bullets.map((b, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className="text-muted-foreground/60">
                    •
                  </span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}

      <section className="border-t pt-6 text-sm text-muted-foreground">
        See also our{" "}
        <Link
          href="/terms"
          className="font-medium text-foreground hover:underline"
        >
          Terms &amp; Conditions
        </Link>
        .
      </section>
    </main>
  );
}
