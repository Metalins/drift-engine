/**
 * /terms — Terms & Conditions. Public, indexable.
 *
 * Jose, 2026-05-21. Plain-language draft. Two points Jose specifically
 * asked to carry: (1) Metalins is not responsible for how the product
 * is used or for decisions made on its output; (2) the verification
 * technology is Metalins's own research and is NOT 100% effective — a
 * signal, not a guarantee.
 *
 * This is a starting draft, not lawyer-reviewed. The governing-law /
 * legal-entity wording is deliberately soft — to be firmed up with
 * counsel and once the operating entity is set.
 *
 * Section bodies live in a data array so the prose stays plain JS
 * strings (apostrophes/dashes need no JSX entity escaping).
 */
import Link from "next/link";

export const metadata = {
  title: "Terms & Conditions — Metalins",
  description:
    "The terms that govern use of Metalins, including how its verification technology should be relied on.",
  alternates: { canonical: "/terms" },
};

const LAST_UPDATED = "21 May 2026";

const SECTIONS: { heading: string; body: string[] }[] = [
  {
    heading: "1. Agreement",
    body: [
      "These Terms & Conditions (the \"Terms\") govern your use of Metalins (\"Metalins\", \"we\", \"us\"). By creating an account or using the service, you agree to them. If you don't agree, please don't use Metalins.",
    ],
  },
  {
    heading: "2. What Metalins does",
    body: [
      "Metalins gives AI agents a verifiable identity and watches for signs that an agent has been swapped, impersonated, or otherwise tampered with. It works from hashes of your agents' activity — never their content. See our Privacy Policy for how that works.",
    ],
  },
  {
    heading: "3. The service is provided \"as is\"",
    body: [
      "Metalins is provided without warranties of any kind, whether express or implied. We work to keep it accurate and available, but we don't promise it will be uninterrupted, error-free, or fit for any particular purpose.",
    ],
  },
  {
    heading: "4. Detection is a signal, not a guarantee",
    body: [
      "Metalins's verification and detection technology is based on our own research. Like any detection system, it is not 100% effective: it can miss a real problem (a false negative) and it can flag activity that turns out to be fine (a false positive).",
      "A Metalins result — a verified status, a drift signal, an alert — is information to inform your judgment. It is not proof, and it is not a guarantee. You should not rely on Metalins as the sole basis for a security, financial, or trust decision.",
    ],
  },
  {
    heading: "5. Your use, and your responsibility",
    body: [
      "You are responsible for how you use Metalins and for any decision you make based on it — including acting on, or choosing not to act on, its signals.",
      "To the maximum extent permitted by law, Metalins is not liable for any loss or damage arising from your use of the product, from reliance on its output, from a false positive or false negative, or from any interruption or unavailability of the service.",
    ],
  },
  {
    heading: "6. Acceptable use",
    body: [
      "Use Metalins lawfully. Don't use it to break the law, infringe anyone's rights, or attempt to disrupt, overload, reverse-engineer, or gain unauthorized access to the service. Only register agents and content you have the right to. You are responsible for keeping your account credentials and API keys secure.",
    ],
  },
  {
    heading: "7. Changes",
    body: [
      "We may change, suspend, or discontinue any part of the service at any time.",
      "We may also update these Terms. Significant changes are reflected by the \"last updated\" date above; continuing to use Metalins after a change means you accept the updated Terms.",
    ],
  },
  {
    heading: "8. Termination",
    body: [
      "You can stop using Metalins at any time and delete your agents and your account. We may suspend or terminate access if these Terms are breached, or where needed to protect the service or other users.",
    ],
  },
  {
    heading: "9. Contact and governing law",
    body: [
      "Questions about these Terms: support@metalins.com. We'll always aim to resolve a concern with you directly first. These Terms are governed by the law of the place where Metalins is established.",
    ],
  },
];

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-8 py-4">
      <header className="space-y-2 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Legal
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Terms &amp; Conditions
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
        </section>
      ))}

      <section className="border-t pt-6 text-sm text-muted-foreground">
        See also our{" "}
        <Link href="/privacy" className="font-medium text-foreground hover:underline">
          Privacy Policy
        </Link>
        .
      </section>
    </main>
  );
}
