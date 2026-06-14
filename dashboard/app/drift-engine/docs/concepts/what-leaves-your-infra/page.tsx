/**
 * /docs/concepts/what-leaves-your-infra — the exact bytes the SDK sends.
 *
 * Issue #6. Diana's blocking trust question before integrating: "what
 * does this thing exfiltrate from my infrastructure?" This page answers
 * it before the objection is raised — it lists, field by field, every
 * request the Python SDK makes to api.metalins.ai, and links each one
 * to the source line that builds it.
 *
 * The load-bearing fact: raw prompts and outputs are sha256-hashed
 * inside your process (sdk-python/metalins/mcp_session.py) before any
 * network call. Only the hex digests travel. Copy is verifiable against
 * the linked source — no claim here that the code doesn't back.
 */
const SRC = "https://github.com/Metalins/metalins/blob/main";
const CLIENT = `${SRC}/sdk-python/metalins/client.py`;
const SESSION = `${SRC}/sdk-python/metalins/mcp_session.py`;

export const metadata = {
  title: "What leaves your infra — Drift Engine docs",
  description:
    "Every request the Drift Engine SDK sends to the server, field by field, with a link to the source line that builds it. Raw prompts and outputs are sha256-hashed in your process before any network call — only hex digests leave your infrastructure.",
  alternates: { canonical: "/drift-engine/docs/concepts/what-leaves-your-infra" },
};

type Field = { name: string; type: string; required: boolean; note: string };

function FieldTable({ fields }: { fields: Field[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left">
          <tr>
            <th className="px-4 py-3 font-medium">Field</th>
            <th className="px-4 py-3 font-medium">Type</th>
            <th className="px-4 py-3 font-medium">Required</th>
            <th className="px-4 py-3 font-medium">What it is</th>
          </tr>
        </thead>
        <tbody className="divide-y text-muted-foreground">
          {fields.map((f) => (
            <tr key={f.name}>
              <td className="px-4 py-3 font-mono text-xs text-foreground">
                {f.name}
              </td>
              <td className="px-4 py-3 font-mono text-xs">{f.type}</td>
              <td className="px-4 py-3">{f.required ? "yes" : "optional"}</td>
              <td className="px-4 py-3">{f.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-mono text-xs underline underline-offset-2 hover:text-foreground"
    >
      {children}
    </a>
  );
}

export default function WhatLeavesYourInfraPage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Concept
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          What leaves your infrastructure
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          Before you put any SDK in your production path, you should know
          exactly what it sends over the wire. This page lists every
          request the Drift Engine Python SDK makes to{" "}
          <span className="font-mono text-sm">api.metalins.ai</span>, field
          by field, and links each one to the line of source that builds
          it. Nothing here is a promise you have to take on faith &mdash;
          it&apos;s in the code you can read.
        </p>
      </header>

      <section className="space-y-5">
        <div className="rounded-lg border-l-4 border-emerald-500 bg-emerald-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            Your prompts and outputs never leave your process
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            When your agent logs an interaction, the SDK runs sha256 over
            the input and the output <strong className="text-foreground">inside
            your process</strong> and sends only the 64-character hex
            digests. The raw text is never put on the wire, never written
            to a request body, never seen by Drift Engine. A digest is
            one-way: we can confirm two interactions match without ever
            learning what they said.
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            See it for yourself:{" "}
            <SourceLink href={`${SESSION}#L130`}>
              mcp_session.py → AgentSession.log_event
            </SourceLink>{" "}
            hashes the payload (<span className="font-mono text-xs">_sha256_hex</span>)
            before it ever calls the client.
          </p>
        </div>

        <div className="rounded-lg border-l-4 border-amber-500 bg-amber-500/5 p-5">
          <h3 className="text-sm font-semibold text-foreground">
            What is sent, in one sentence
          </h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Identity metadata you choose (an agent name, optionally a model
            or framework string), sha256 hashes of your interactions,
            cryptographic answers to verification challenges, and a small
            set of <strong className="text-foreground">low-resolution
            structural signals</strong> about each turn — lengths, format
            flags, sentence counts, the <em>names</em> of tools called,
            latency, and a salted, irreversible fingerprint of the
            output&apos;s vocabulary. No prompts, no completions, no tool
            arguments, no customer data.
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Every request, field by field
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The SDK is a thin client over the HTTP API &mdash; one method per
          endpoint, no hidden calls. Each request below is everything the
          method puts in the body. Authentication is a single{" "}
          <span className="font-mono text-xs">Authorization: Bearer &lt;api_key&gt;</span>{" "}
          header on every call.
        </p>

        {/* create_agent */}
        <div className="space-y-2 pt-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-base font-semibold text-foreground">
              Register an agent
            </h3>
            <span className="font-mono text-xs text-muted-foreground">
              POST /v1/agents
            </span>
            <SourceLink href={`${CLIENT}#L65`}>client.py → create_agent</SourceLink>
          </div>
          <p className="text-sm text-muted-foreground">
            Called once when you first register an agent.
          </p>
          <FieldTable
            fields={[
              { name: "name", type: "string", required: true, note: "A label you pick for the agent. Your choice — use a pseudonym if you prefer." },
              { name: "model", type: "string", required: false, note: "Optional model string you pass (e.g. \"gpt-4o\"). Only sent if you set it." },
              { name: "framework", type: "string", required: false, note: "Optional framework string (e.g. \"langchain\"). Only sent if you set it." },
              { name: "metadata", type: "object", required: false, note: "Optional free-form dict you control. The SDK sends exactly what you put here — nothing implicit." },
            ]}
          />
        </div>

        {/* log_event */}
        <div className="space-y-2 pt-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-base font-semibold text-foreground">
              Log an interaction
            </h3>
            <span className="font-mono text-xs text-muted-foreground">
              POST /v1/agents/&#123;id&#125;/events
            </span>
            <SourceLink href={`${CLIENT}#L88`}>client.py → log_event</SourceLink>
          </div>
          <p className="text-sm text-muted-foreground">
            The hot path. Sent once per interaction you choose to log.
          </p>
          <FieldTable
            fields={[
              { name: "input_hash", type: "string (sha256 hex)", required: true, note: "sha256 of your input, computed in your process. The raw input is not sent." },
              { name: "output_hash", type: "string (sha256 hex)", required: true, note: "sha256 of your output, computed in your process. The raw output is not sent." },
              { name: "metadata.behavioral", type: "object", required: false, note: "Low-resolution structural signals about the turn, computed in your process before hashing and sent by default (opt out with compute_behavioral=False). Field-by-field below — never the raw text." },
              { name: "metadata.*", type: "object", required: false, note: "Any other keys are a free-form dict you control. Send only what you want stored." },
            ]}
          />

          <div className="mt-4 rounded-lg border-l-4 border-sky-500 bg-sky-500/5 p-5">
            <h4 className="text-sm font-semibold text-foreground">
              The behavioral block — how we baseline without reading content
            </h4>
            <p className="mt-2 text-sm text-muted-foreground">
              To tell &ldquo;the agent running today behaves like the one
              you deployed&rdquo; apart from &ldquo;something changed,&rdquo;
              the engine needs <em>shape</em>, not text. So the SDK measures
              a handful of structural properties of each turn{" "}
              <strong className="text-foreground">in your process, before
              hashing</strong>, and sends them as{" "}
              <span className="font-mono text-xs">metadata.behavioral</span>.
              These are lengths, booleans, counts, and one keyed fingerprint
              &mdash; deliberately too coarse to reconstruct what was said.
              This is the part competitors that pipe your full traffic
              through their servers can&apos;t match: continuous behavioral
              monitoring from signal that can&apos;t be reversed into
              content.
            </p>
            <div className="mt-4">
              <FieldTable
                fields={[
                  { name: "output_length_chars / _tokens", type: "int", required: false, note: "How long the output was. A number, not the text." },
                  { name: "input_length_chars", type: "int", required: false, note: "How long the input was. A number, not the text." },
                  { name: "sentence_count_output", type: "int", required: false, note: "Number of sentences in the output." },
                  { name: "mean_sentence_length_output", type: "float", required: false, note: "Average words per sentence." },
                  { name: "had_code_block / had_list / had_markdown", type: "bool", required: false, note: "Format flags: did the output contain a code block, a list, markdown?" },
                  { name: "format_markers", type: "object<bool>", required: false, note: "The same format flags plus a json marker, as a small bool map." },
                  { name: "tool_calls", type: "string[]", required: false, note: "The NAMES of tools the agent called — never their arguments or results." },
                  { name: "latency_ms", type: "float", required: false, note: "Wall-clock time for the turn, if measured." },
                  { name: "error_class", type: "string", required: false, note: "How the turn ended: none, timeout, refusal, retry, tool_error, or parse_error." },
                  { name: "token_bag_lsh", type: "string (hex)", required: false, note: "A salted 64-bit SimHash of the output's vocabulary — comparable across turns, irreversible, and only emitted when the output has 5+ distinct tokens so a short reply can't be brute-forced." },
                ]}
              />
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              Honest caveat: these are <em>low-resolution and hard to
              invert</em>, not a cryptographic guarantee like the hashes.
              Lengths and counts are exact-ish because the engine needs the
              signal. If you handle highly sensitive traffic, treat the
              behavioral block as client-attested structure, and opt out
              entirely with{" "}
              <span className="font-mono text-xs">compute_behavioral=False</span>{" "}
              &mdash; identity verification still works on the hashes alone.
              See{" "}
              <SourceLink href={`${SRC}/sdk-python/metalins/behavioral.py`}>
                sdk-python/metalins/behavioral.py
              </SourceLink>{" "}
              for the exact extraction.
            </p>
          </div>
        </div>

        {/* answer_check */}
        <div className="space-y-2 pt-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-base font-semibold text-foreground">
              Answer a verification check
            </h3>
            <span className="font-mono text-xs text-muted-foreground">
              POST /v1/agents/&#123;id&#125;/checks/&#123;check_id&#125;
            </span>
            <SourceLink href={`${CLIENT}#L112`}>client.py → answer_check</SourceLink>
          </div>
          <p className="text-sm text-muted-foreground">
            The server occasionally challenges the agent to prove it still
            holds the secret. The answer is a hash derived from the local
            digest chain, a server nonce, and the agent secret &mdash; the
            secret itself is never sent (see{" "}
            <SourceLink href={`${SESSION}#L58`}>compute_check_answer</SourceLink>).
          </p>
          <FieldTable
            fields={[
              { name: "answer", type: "string (sha256 hex)", required: false, note: "The computed challenge response for a well-formed check. A derived hash, not the secret." },
              { name: "decline_reason", type: "string", required: false, note: "Sent instead of answer when the agent recognizes a malformed check and refuses it." },
              { name: "progress", type: "integer", required: false, note: "Optional progress marker for multi-step checks. Only sent if set." },
            ]}
          />
        </div>

        {/* issue_proof */}
        <div className="space-y-2 pt-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-base font-semibold text-foreground">
              Issue an identity proof
            </h3>
            <span className="font-mono text-xs text-muted-foreground">
              POST /v1/agents/&#123;id&#125;/proofs
            </span>
            <SourceLink href={`${CLIENT}#L160`}>client.py → issue_proof</SourceLink>
          </div>
          <p className="text-sm text-muted-foreground">
            Mints a short-lived signed token the agent can hand to a
            relying party.
          </p>
          <FieldTable
            fields={[
              { name: "ttl_seconds", type: "integer", required: true, note: "Lifetime of the proof: 300, 3600, or 86400 seconds." },
              { name: "scope", type: "string", required: false, note: "Optional scope string for the proof. Only sent if set." },
            ]}
          />
        </div>

        {/* read + revoke */}
        <div className="space-y-2 pt-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-base font-semibold text-foreground">
              Reads and revoke
            </h3>
            <SourceLink href={CLIENT}>client.py</SourceLink>
          </div>
          <p className="text-sm text-muted-foreground">
            The remaining calls carry no interaction data at all.{" "}
            <span className="font-mono text-xs">GET /v1/agents</span>,{" "}
            <span className="font-mono text-xs">GET /v1/agents/&#123;id&#125;</span>, and{" "}
            <span className="font-mono text-xs">GET /v1/agents/&#123;id&#125;/checks</span>{" "}
            send only the agent id in the URL.{" "}
            <span className="font-mono text-xs">DELETE /v1/agents/&#123;id&#125;</span>{" "}
            revokes an agent and sends at most an optional{" "}
            <span className="font-mono text-xs">reason</span> string as a
            query parameter.
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">
          Read the whole client
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          There is no out-of-band telemetry. Every network call the SDK
          makes lives in one file you can audit end to end:{" "}
          <SourceLink href={CLIENT}>sdk-python/metalins/client.py</SourceLink>.
          The hashing that keeps your data local lives in{" "}
          <SourceLink href={SESSION}>sdk-python/metalins/mcp_session.py</SourceLink>.
        </p>
      </section>

      <div className="rounded-lg border bg-muted/30 p-5">
        <p className="text-sm text-muted-foreground">
          <strong className="text-foreground">In one line:</strong> what
          leaves your infrastructure is a name you chose, sha256 digests of
          interactions you opted to log, cryptographic challenge answers,
          and a handful of low-resolution structural signals about each turn
          &mdash; never your prompts, outputs, tool arguments, or customer
          data. And you can verify every word of that against the linked
          source.
        </p>
      </div>
    </main>
  );
}
