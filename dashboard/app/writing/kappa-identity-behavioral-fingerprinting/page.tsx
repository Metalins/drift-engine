import type { Metadata } from "next";
import Link from "next/link";

const TITLE =
  "κ-Identity: Behavioral Fingerprinting for Continuous Verification of LLM Agents";
const DESCRIPTION =
  "A framework for continuous identity verification of autonomous AI agents using behavioral fingerprinting. Detects model substitution, prompt injection, and drift — without access to model weights, raw prompts, or outputs.";
const DOI = "10.5281/zenodo.20693202";
const DOI_URL = "https://doi.org/10.5281/zenodo.20693202";
const CANONICAL =
  "https://metalins.com/writing/kappa-identity-behavioral-fingerprinting";

export const metadata: Metadata = {
  title: `${TITLE} — Metalins`,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: CANONICAL,
    type: "article",
    authors: ["Jose Miguel Hernandez Perez"],
    publishedTime: "2026-06-15",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  alternates: {
    canonical: CANONICAL,
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "ScholarlyArticle",
  headline: TITLE,
  description: DESCRIPTION,
  author: {
    "@type": "Person",
    name: "Jose Miguel Hernandez Perez",
    url: "https://github.com/josemiguelhpz",
  },
  publisher: {
    "@type": "Organization",
    name: "Metalins",
    url: "https://metalins.com",
  },
  datePublished: "2026-06-15",
  identifier: {
    "@type": "PropertyValue",
    propertyID: "DOI",
    value: DOI,
  },
  url: DOI_URL,
  sameAs: DOI_URL,
  keywords: [
    "behavioral fingerprinting",
    "AI agents",
    "LLM agents",
    "model verification",
    "drift detection",
    "prompt injection",
    "identity",
    "attestation",
  ],
};

export default function KappaIdentityPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main className="mx-auto max-w-2xl py-12">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-muted-foreground">
          <Link href="/writing" className="hover:text-foreground">
            Writing
          </Link>
          <span className="mx-2">→</span>
          <span>κ-Identity</span>
        </nav>

        {/* Header */}
        <header className="mb-10">
          <div className="mb-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
            <time dateTime="2026-06-15">June 15, 2026</time>
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono">paper</span>
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono">behavioral-fingerprinting</span>
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono">ai-agents</span>
          </div>
          <h1 className="text-3xl font-bold leading-tight tracking-tight">
            κ-Identity: Behavioral Fingerprinting for Continuous Verification of
            LLM Agents
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">
            <a
              href="https://github.com/josemiguelhpz"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:no-underline"
            >
              Jose Miguel Hernandez Perez
            </a>{" "}
            · Metalins Research · v0.3
          </p>
          <a
            href={DOI_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block rounded border px-3 py-1.5 text-sm font-medium hover:bg-accent"
          >
            Read full paper → DOI {DOI}
          </a>
        </header>

        <div className="prose prose-neutral dark:prose-invert max-w-none text-sm leading-relaxed">

          {/* Abstract */}
          <section className="mb-8 rounded-lg border bg-muted/40 p-5">
            <h2 className="mt-0 text-base font-semibold">Abstract</h2>
            <p>
              We introduce <strong>κ-Identity</strong>, a primitive for the
              continuous behavioral identity of autonomous LLM agents in
              production. κ-Identity is the specialization to LLM agents of a
              broader framework in which the <em>identity</em> of any
              mutable-substrate process is the persistent correlational
              structure between that process and its environment, integrated
              over time.
            </p>
            <p>
              κ-Identity is measured by <strong>behavioral fingerprinting</strong>:
              a privacy-preserving method that extracts low-resolution structural
              features of each input-output event client-side, learns a per-agent
              baseline distribution from organic traffic, and runs windowed
              two-sample tests against that baseline to detect model substitution,
              sustained injection, and drift — without access to model weights,
              raw prompts, or raw responses.
            </p>
            <p>
              Verdicts are issued as <strong>κ-Proofs</strong>: signed JSON Web
              Tokens that any third party can verify offline against a public
              JWKS, without an account with the verifier, making behavioral
              attestation portable across organizational trust boundaries.
            </p>
          </section>

          {/* Problem */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold">The problem</h2>
            <p>
              Authentication answers a time-bounded question: <em>who is
              connecting?</em> For deterministic software, this is sufficient —
              the entity that proved its key is the entity that runs. Autonomous
              LLM agents break this assumption along two axes:
            </p>
            <ul>
              <li>
                <strong>Agents are stochastic.</strong> {/* metalins:internal-allowed — academic term in research paper */} The same agent produces
                materially different outputs for the same input. Fingerprinting
                by exact-matching outputs is impossible by construction.
              </li>
              <li>
                <strong>Agents are mutable at runtime.</strong> The model
                serving an endpoint can be silently substituted — a cheaper
                variant, a fine-tuned descendant, or an adversarial replacement
                — with no visible change to the API key being presented. System
                prompts get edited. Retrieval stores get poisoned. Tool sets get
                updated. None of this is visible to a verifier that only checks
                credentials.
              </li>
            </ul>
            <p>
              The gap: there is no continuous, credential-independent signal
              that the agent active today is the same agent that was deployed
              and verified last week.
            </p>
          </section>

          {/* Framework */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold">The framework</h2>
            <p>
              κ-Identity formalizes identity as the{" "}
              <strong>
                persistent correlational structure between a process and its
                environment, integrated over time
              </strong>
              . Operationally: conditional mutual information {/* metalins:internal-allowed — mathematical definition in research paper */} between past and
              future behavior given environment, exceeding a non-trivial
              threshold over a minimum temporal window.
            </p>
            <p>This framework admits cross-domain instantiations:</p>
            <ul>
              <li>
                <strong>Quantum systems</strong> — persistent correlations under
                repeated measurement
              </li>
              <li>
                <strong>Humans</strong> — behavioral biometrics (gait, typing
                rhythm, writing style)
              </li>
              <li>
                <strong>Computer processes</strong> — runtime integrity
                attestation via system call patterns
              </li>
              <li>
                <strong>LLM agents</strong> — κ-Identity, the specialization
                developed here
              </li>
            </ul>
            <p>The framework also exposes four structural limits:</p>
            <ol>
              <li>
                Systems sharing all observable statistics are behaviorally
                indistinguishable — behavioral identity cannot be finer than
                behavioral equivalence.
              </li>
              <li>
                Behavioral channels cannot measure intention — an agent
                programmed to mimic a target is indistinguishable from the
                target at the behavioral layer.
              </li>
              <li>
                Substrate-access strategies (reading model weights) cannot
                recover behavioral identity — they answer a different question.
              </li>
              <li>
                Operationally defensible attestation requires multi-modal
                composition — behavioral evidence alone is necessary but not
                sufficient.
              </li>
            </ol>
          </section>

          {/* Measurement */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold">Measuring κ-Identity</h2>
            <p>
              Behavioral fingerprinting works in three stages:
            </p>
            <ol>
              <li>
                <strong>Feature extraction (client-side).</strong> Low-resolution
                structural features — token-count distributions, response timing,
                entropy, tool call patterns — are extracted from each event
                without retaining raw content. Privacy is preserved by
                construction: the verifier never sees prompts or outputs.
              </li>
              <li>
                <strong>Baseline learning.</strong> A per-agent statistical model
                is built from organic traffic over a calibration window. The
                baseline captures the agent&apos;s behavioral fingerprint under
                normal operation.
              </li>
              <li>
                <strong>Continuous testing.</strong> Windowed two-sample tests
                compare fresh activity against the baseline. Significant
                divergence triggers an alert — a signal that something about
                the agent has changed.
              </li>
            </ol>
            <p>
              The method detects <strong>model substitution</strong> (a different
              model now serves the endpoint), <strong>sustained prompt
              injection</strong> (the agent&apos;s behavior has been persistently
              altered by injected instructions), and{" "}
              <strong>behavioral drift</strong> (gradual shift from the
              established baseline, possibly from fine-tuning or context
              contamination).
            </p>
          </section>

          {/* Attestation */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold">κ-Proofs: portable attestation</h2>
            <p>
              A κ-Proof is a signed JWT issued by the verifier after a
              measurement window closes. It encodes:
            </p>
            <ul>
              <li>The agent identifier and the time window covered</li>
              <li>
                The verdict: whether κ-Identity was maintained over the window
              </li>
              <li>A cryptographic signature from the verifier&apos;s private key</li>
            </ul>
            <p>
              Any third party — an auditor, a compliance system, a downstream
              service — can verify the proof offline against the verifier&apos;s
              public JWKS without an account, without access to the underlying
              events, and without trusting any party other than the verifier
              whose public key they already hold. Behavioral attestation becomes
              portable across organizational trust boundaries.
            </p>
          </section>

          {/* Implementation */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold">
              Production instantiation: Drift Engine
            </h2>
            <p>
              <strong>Drift Engine</strong> is the production implementation of
              this framework, published by Metalins as an open-source,
              self-hosted tool (AGPL-3.0). It implements the full κ-Identity
              stack: behavioral feature extraction via the Python SDK, baseline
              learning and windowed testing in the κ-engine, κ-Proof issuance
              via the FastAPI server, and a dashboard for continuous monitoring.
            </p>
            <p>
              Drift Engine runs on your own infrastructure. No data leaves your
              perimeter. The verifier key pair is generated locally on first
              boot.
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <a
                href="https://github.com/Metalins/drift-engine"
                target="_blank"
                rel="noopener noreferrer"
                className="rounded border px-3 py-1.5 text-sm font-medium hover:bg-accent"
              >
                GitHub →
              </a>
              <Link
                href="/drift-engine/docs/getting-started"
                className="rounded border px-3 py-1.5 text-sm font-medium hover:bg-accent"
              >
                Self-host Drift Engine →
              </Link>
            </div>
          </section>

          {/* Full paper */}
          <section className="rounded-lg border p-5">
            <h2 className="mt-0 text-base font-semibold">Full paper</h2>
            <p className="text-muted-foreground">
              The complete paper — including formal definitions, cross-domain
              proofs, threat model analysis, limitations, and related work — is
              available on Zenodo.
            </p>
            <a
              href={DOI_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block text-sm font-medium underline hover:no-underline"
            >
              Read on Zenodo → DOI {DOI}
            </a>
          </section>
        </div>
      </main>
    </>
  );
}
