/**
 * /docs/reference/developer-api — Reference for the developer HTTP API.
 *
 * Sprint UX-5.17.API3 (task #920). The developer API is the MVP's
 * primary surface: a developer with their own agent code calls it
 * directly; the Python SDK is an ergonomic wrapper over the same
 * endpoints. This page is the full, public, indexable reference —
 * the per-agent /agents/[id]/api/setup page links here.
 *
 * Content rule: customer-facing, D-PROD.18 — no internal mechanism
 * names. The API speaks "verification check", "tier", "verification"
 * (two layers), never the engine's taxonomy.
 *
 * Snippet code is rendered from the shared `lib/api-snippets` builders
 * — the same source the in-dashboard /agents/[id]/api/setup page uses
 * — so the docs and the setup flow never drift apart.
 */
import {
  PIP_INSTALL,
  eventCurlSnippet,
  sdkRegisterSnippet,
  sdkAttachSnippet,
} from "@/lib/api-snippets";

export const metadata = {
  title: "HTTP API reference — Drift Engine docs",
  description:
    "The Drift Engine developer HTTP API: register agents, stream events, " +
    "answer verification checks, issue identity proofs. Curl + Python SDK.",
  alternates: { canonical: "/drift-engine/docs/reference/developer-api" },
};

const BASE = "https://api.metalins.ai/v1";

function Endpoint({
  method,
  path,
  children,
}: {
  method: string;
  path: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-card/60 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-foreground px-2 py-0.5 font-mono text-xs font-semibold text-background">
          {method}
        </span>
        <code className="break-all text-sm font-medium">{path}</code>
      </div>
      <div className="mt-3 space-y-3 text-sm text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

function Code({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/60 p-3 text-xs leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

/**
 * Collapsible "Example response" block. Native <details> — works with
 * no JavaScript, and the page stays scannable: a reader sees the
 * endpoint and its description, and opens the example only if they
 * want to see the exact shape they'll get back. `note` is an optional
 * line under the JSON, used to point at a deeper doc for fields whose
 * meaning needs more than a one-liner.
 */
function ResponseExample({
  json,
  label = "Example response",
  note,
}: {
  json: string;
  label?: string;
  note?: React.ReactNode;
}) {
  return (
    <details className="rounded-md border bg-muted/20">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-foreground hover:bg-muted/40">
        {label}
      </summary>
      <div className="space-y-2 border-t p-3">
        <Code>{json}</Code>
        {note && (
          <div className="text-xs leading-relaxed text-muted-foreground">
            {note}
          </div>
        )}
      </div>
    </details>
  );
}

export default function DeveloperApiReferencePage() {
  return (
    <main className="space-y-10">
      <header className="space-y-3 border-b pb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Reference
        </p>
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          HTTP API
        </h1>
        <p className="max-w-3xl text-muted-foreground">
          Register an agent, stream it events,
          read its verification status, issue identity proofs &mdash;
          from any language that can make an HTTPS request. The Python
          SDK is an ergonomic wrapper over exactly these endpoints; you
          never have to use it.
        </p>
      </header>

      {/* ----- Basics --------------------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Basics</h2>
        <p className="text-sm text-muted-foreground">
          Base URL <code className="rounded bg-muted px-1 py-0.5 text-xs">{BASE}</code>.
          Authenticate every request with an API key as a bearer token:
        </p>
        <Code>{`Authorization: Bearer YOUR_API_KEY`}</Code>
        <p className="text-sm text-muted-foreground">
          Mint a key from the dashboard. The{" "}
          <a
            href="/keys"
            className="font-medium text-foreground underline underline-offset-2"
          >
            API keys page
          </a>{" "}
          issues a key that works across every agent in your account; you
          can also mint one inside an agent&apos;s <em>HTTP API / SDK</em>{" "}
          setup step. The plaintext key is shown <strong>once</strong>{" "}
          &mdash; copy it then, we never store it in the clear. Lost a key,
          or want to rotate it? Revoke the old one and mint a fresh one
          from the same page.
        </p>
        <p className="text-sm text-muted-foreground">
          Raw prompt and response text never leave your side: events carry
          sha256 hashes you compute locally, plus an optional set of
          low-resolution structural signals (lengths, format flags, tool
          names, a salted vocabulary fingerprint) the SDK adds for drift
          detection &mdash; never the content. An API key
          authenticates <em>you</em>; each agent additionally has its own{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            agent_secret
          </code>{" "}
          (returned when the agent is registered) that it uses to answer
          verification checks.
        </p>
      </section>

      {/* ----- The loop ------------------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">
          The model
        </h2>
        <p className="text-sm text-muted-foreground">
          One paradigm: <strong>log events, the engine scores, you read
          the status.</strong> Register an agent once, stream it an event
          per interaction, and read its verification status whenever you
          want. When the engine wants the agent to prove continuity it
          returns a <em>verification check</em> on a{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            POST /events
          </code>{" "}
          response; you answer it on the next call.
        </p>
      </section>

      {/* ----- Endpoints ------------------------------------------------ */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Endpoints</h2>

        <Endpoint method="POST" path="/v1/agents">
          <p>
            Register an agent. The body takes a <code>name</code> and an
            optional <code>metadata</code> object. Set{" "}
            <code>agent_profile</code> in <code>metadata</code> (one of{" "}
            <code>deterministic</code>, <code>assistant</code>, or{" "}
            <code>autonomous</code>) so the engine learns its baseline
            to match how your agent actually behaves.
          </p>
          <p>
            The response returns <code>agent_id</code> and{" "}
            <code>agent_secret</code>. The secret is shown{" "}
            <strong>once</strong> &mdash; it is what the agent uses to
            answer verification checks, so write it somewhere durable.
            Lost it? Reissue a fresh one from the agent&apos;s settings in
            the dashboard.
          </p>
          <Code>{`curl -X POST ${BASE}/agents \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{ "name": "billing-assistant", "metadata": { "agent_profile": "deterministic" } }'`}</Code>
          <ResponseExample
            label="Example response — 201 Created"
            json={`{
  "agent_id": "agt_7k2m4x9q",
  "agent_secret": "ams_3f9b1c7d2e...",
  "created_at": "2026-05-21T18:00:00Z",
  "secret_warning": "Store agent_secret now — it is shown only once and is required for the agent to answer verification checks."
}`}
          />
          <div className="rounded-md border bg-muted/40 p-3 text-xs">
            <p className="font-medium text-foreground">
              Prefer the dashboard? You don&apos;t have to call this
              endpoint at all.
            </p>
            <p className="mt-1.5">
              Create the agent from{" "}
              <a
                href="/agents/new"
                className="font-medium text-foreground underline underline-offset-2"
              >
                New agent
              </a>{" "}
              in the dashboard &mdash; it shows you the{" "}
              <code>agent_id</code> and <code>agent_secret</code> on the
              same screen, and you pick the profile from a menu. Then point
              your code at that existing agent with{" "}
              <code>metalins.Agent.attach(api_key, agent_id, agent_secret)</code>{" "}
              instead of constructing a fresh <code>Agent</code> (see the
              SDK section below). Calling <code>POST /v1/agents</code> and
              creating it in the dashboard land you in the same place: an
              agent you can stream events to and read status from.
            </p>
          </div>
        </Endpoint>

        <Endpoint method="POST" path="/v1/agents/{id}/events">
          <p>
            Log one interaction. Body carries <code>input_hash</code> and{" "}
            <code>output_hash</code> (sha256 hex, hashed locally), plus
            optional <code>metadata</code>. The response returns the
            running <code>event_count</code> and{" "}
            <code>pending_checks</code> &mdash; any verification checks to
            answer.
          </p>
          <Code>{eventCurlSnippet()}</Code>
          <ResponseExample
            json={`{
  "agent_id": "agt_7k2m4x9q",
  "event_count": 41,
  "pending_checks": [
    {
      "check_id": "chk_3a9f1e",
      "target_event_count": 41,
      "nonce": "b1d4c8a2f6",
      "issued_at": "2026-05-21T18:00:02Z",
      "expires_at": "2026-05-21T18:05:02Z"
    }
  ]
}`}
            note={
              <>
                Most of the time <code>pending_checks</code> is{" "}
                <code>[]</code>. When it isn&apos;t, each item is a
                verification check to answer with{" "}
                <code>POST /v1/agents/{"{id}"}/checks/{"{check_id}"}</code>{" "}
                (next endpoint) before its <code>expires_at</code>.
              </>
            }
          />
        </Endpoint>

        <Endpoint method="POST" path="/v1/agents/{id}/checks/{check_id}">
          <p>
            Answer a verification check returned in a{" "}
            <code>pending_checks</code> array. Send the computed{" "}
            <code>answer</code>, or a <code>decline_reason</code> if the
            check is malformed and you refuse it. The SDK computes the
            answer for you; the math is documented with the SDK.
          </p>
          <ResponseExample
            json={`{
  "check_id": "chk_3a9f1e",
  "accepted": true,
  "detail": "ok"
}`}
            note={
              <>
                <code>accepted</code> is <code>false</code> when the
                answer was wrong or the check had already expired &mdash;{" "}
                <code>detail</code> says which. A repeatedly{" "}
                <code>false</code> result surfaces on the agent&apos;s
                status as a cryptographic{" "}
                <code>action_required</code>.
              </>
            }
          />
        </Endpoint>

        <Endpoint method="GET" path="/v1/agents/{id}">
          <p>
            Read one agent&apos;s verification status &mdash; the lean,
            stable contract you poll after connecting. Two independent
            layers, a tier, and any plain-English items needing your
            attention.
          </p>
          <ResponseExample
            json={`{
  "agent_id": "agt_7k2m4x9q",
  "name": "billing-assistant",
  "created_at": "2026-05-20T09:00:00Z",
  "event_count": 41,
  "last_active": "2026-05-21T18:00:00Z",
  "tier": "T2",
  "verification": { "cryptographic": "verified", "behavioral": "building" },
  "attention": [
    {
      "message": "This agent isn't answering its memory checks — 3 recent challenges expired with no response.",
      "code": "probes_unanswered",
      "learn_more": {
        "what": "Memory checks were sent to your agent and expired with no answer at all.",
        "self_resolving": "Usually operational rather than a compromise — the agent was offline or its integration wasn't running. It clears once the agent starts answering checks again.",
        "action": "Confirm the agent is online and the SDK component that fetches and answers checks is running."
      }
    }
  ]
}`}
            note={
              <ul className="space-y-1.5">
                <li>
                  <code>verification.cryptographic</code> &mdash; the
                  binary identity layer: <code>verified</code>,{" "}
                  <code>building</code>, or <code>action_required</code>.
                  See{" "}
                  <a
                    href="/drift-engine/docs/concepts/cryptographic-identity"
                    className="underline"
                  >
                    cryptographic identity
                  </a>
                  .
                </li>
                <li>
                  <code>verification.behavioral</code> &mdash; the gradual
                  pattern layer; reads <code>building</code> until enough
                  events have landed for the pattern to be trustworthy.
                  See{" "}
                  <a
                    href="/drift-engine/docs/concepts/behavioral-baseline"
                    className="underline"
                  >
                    behavior pattern
                  </a>
                  .
                </li>
                <li>
                  <code>tier</code> &mdash; <code>T0</code>&ndash;
                  <code>T3</code>, how much is actively protecting the
                  agent. See{" "}
                  <a href="/drift-engine/docs/concepts/tiers" className="underline">
                    identity tiers
                  </a>
                  .
                </li>
                <li>
                  <code>attention</code> &mdash; items to act on; an empty
                  array means nothing needs you right now. Each item is an
                  object: a <code>message</code> safe to show a user as-is,
                  a stable <code>code</code>, and a <code>learn_more</code>{" "}
                  object (<code>what</code> / <code>self_resolving</code> /{" "}
                  <code>action</code>) explaining what the signal means,
                  whether it clears on its own, and the next step.{" "}
                  <code>learn_more</code> is <code>null</code> for the rare
                  item with no extra guidance. The{" "}
                  <a
                    href="/drift-engine/docs/concepts/drift-detection"
                    className="underline"
                  >
                    drift signals
                  </a>{" "}
                  and{" "}
                  <a
                    href="/drift-engine/docs/concepts/integration-lifecycle"
                    className="underline"
                  >
                    integration lifecycle
                  </a>{" "}
                  pages explain what prompts these messages.
                </li>
              </ul>
            }
          />
        </Endpoint>

        <Endpoint method="GET" path="/v1/agents">
          <p>
            List the agents in your account &mdash; a lean summary per
            agent. Paginated with <code>limit</code> /{" "}
            <code>offset</code> query params.
          </p>
          <ResponseExample
            json={`{
  "agents": [
    {
      "agent_id": "agt_7k2m4x9q",
      "name": "billing-assistant",
      "event_count": 41,
      "last_active": "2026-05-21T18:00:00Z",
      "tier": "T2",
      "verification": { "cryptographic": "verified", "behavioral": "building" },
      "needs_attention": false
    }
  ],
  "count": 1
}`}
            note={
              <>
                Each entry is a summary &mdash; <code>needs_attention</code>{" "}
                is a boolean here. Call{" "}
                <code>GET /v1/agents/{"{id}"}</code> for one agent&apos;s
                full status, including the <code>attention</code> message
                list.
              </>
            }
          />
        </Endpoint>

        <Endpoint method="POST" path="/v1/agents/{id}/proofs">
          <p>
            Issue a signed identity proof an agent can hand to another
            party (agent-to-agent). Optional <code>scope</code> and{" "}
            <code>ttl_seconds</code> (300 / 3600 / 86400). The holder
            verifies it at the public, no-auth{" "}
            <a href="/drift-engine/docs/reference/verify-proof" className="underline">
              verify-proof endpoint
            </a>
            .
          </p>
          <ResponseExample
            label="Example response — 201 Created"
            json={`{
  "proof_id": "prf_5h8d2k",
  "agent_id": "agt_7k2m4x9q",
  "proof": "eyJhbGciOi...<signed token>",
  "issued_at": "2026-05-21T18:00:00Z",
  "expires_at": "2026-05-21T19:00:00Z",
  "scope": "read"
}`}
            note={
              <>
                Hand the <code>proof</code> token to the other party;
                they check it at the{" "}
                <a
                  href="/drift-engine/docs/reference/verify-proof"
                  className="underline"
                >
                  verify-proof endpoint
                </a>
                . The short <code>proof_id</code> resolves the same proof
                without passing the full token around.
              </>
            }
          />
        </Endpoint>

        <Endpoint method="DELETE" path="/v1/agents/{id}">
          <p>
            Revoke an agent. Permanent: the agent stops verifying and any
            proof it issued resolves as no longer active. Pass an optional{" "}
            <code>?reason=</code> for the audit record.
          </p>
          <ResponseExample
            json={`{
  "agent_id": "agt_7k2m4x9q",
  "revoked_at": "2026-05-21T18:00:00Z"
}`}
          />
        </Endpoint>
      </section>

      {/* ----- Errors --------------------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Errors</h2>
        <p className="text-sm text-muted-foreground">
          Errors use standard HTTP status codes. The body is always JSON
          with a <code className="rounded bg-muted px-1 py-0.5 text-xs">
            detail
          </code>{" "}
          string you can show or log:
        </p>
        <Code>{`{ "detail": "Provide either 'answer' or 'decline_reason'." }`}</Code>
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          <li>
            <code>400</code> / <code>422</code> &mdash; the request body is
            malformed or a field is missing; <code>detail</code> names the
            problem.
          </li>
          <li>
            <code>401</code> &mdash; the API key is missing, malformed, or
            revoked. Check the <code>Authorization</code> header.
          </li>
          <li>
            <code>404</code> &mdash; no agent with that <code>id</code> in
            your account. (Agents are scoped to the key&apos;s account, so
            another account&apos;s agent reads as not found.)
          </li>
          <li>
            <code>5xx</code> &mdash; a server-side problem; the request was
            well-formed, so it is safe to retry after a short backoff.
          </li>
        </ul>
      </section>

      {/* ----- Python SDK ----------------------------------------------- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">
          Python SDK
        </h2>
        <p className="text-sm text-muted-foreground">
          The SDK wraps the endpoints above and computes verification-check
          answers for you. Nothing it does is unavailable over plain HTTP.
          The <code className="rounded bg-muted px-1 py-0.5">Agent</code>{" "}
          facade is the quickest path: register once, then a background
          loop answers verification checks whether or not the agent is
          busy.
        </p>
        <Code>{PIP_INSTALL}</Code>
        <Code>{sdkRegisterSnippet()}</Code>
        <p className="text-sm text-muted-foreground">
          Already created the agent in the dashboard? Don&apos;t call{" "}
          <code className="rounded bg-muted px-1 py-0.5">Agent(...)</code>{" "}
          &mdash; that registers a new one. Use{" "}
          <code className="rounded bg-muted px-1 py-0.5">Agent.attach</code>{" "}
          with the <code>agent_id</code> and <code>agent_secret</code> the
          dashboard showed you, and the SDK adopts that existing agent:
        </p>
        <Code>{sdkAttachSnippet()}</Code>
        <p className="text-sm text-muted-foreground">
          For finer control,{" "}
          <code className="rounded bg-muted px-1 py-0.5">Client</code> and{" "}
          <code className="rounded bg-muted px-1 py-0.5">AgentSession</code>{" "}
          expose the protocol primitives directly — the SDK README walks
          that path.
        </p>
      </section>

      {/* ----- Relying party ------------------------------------------- */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">
          The relying-party side
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Verifying a proof someone handed you needs no account and no
          API key &mdash; see the{" "}
          <a href="/drift-engine/docs/reference/verify-proof" className="underline">
            verify-proof reference
          </a>
          .
        </p>
      </section>

      {/* ----- Other ways to connect ----------------------------------- */}
      <section className="space-y-3 border-t pt-6">
        <h2 className="text-lg font-semibold tracking-tight">
          Other ways to connect
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The HTTP API / SDK is the primary path, for backend agents you
          run yourself. If your agent lives inside a chat or editor
          client, <a href="/drift-engine/docs/getting-started/mcp-setup" className="underline">
            MCP setup
          </a>{" "}
          is one line of config. If it&apos;s a public bot, the{" "}
          <a
            href="/drift-engine/docs/getting-started/bot-watcher"
            className="underline"
          >
            public-bot watcher
          </a>{" "}
          needs no code at all.
        </p>
      </section>
    </main>
  );
}
