/**
 * Shared HTTP API / SDK snippet builders — one source of truth for the
 * code examples that appear in both the customer-facing docs and the
 * in-dashboard setup flow.
 *
 * Mirrors the pattern of `lib/mcp-snippets.ts`: the per-agent setup
 * page (`/agents/[id]/api/setup`) and the public docs
 * (`/docs/reference/developer-api`, `/docs/getting-started`) used to
 * carry their own near-identical copies of the SDK / curl snippets,
 * which drifted apart. Now both import from here — edit a snippet once
 * and every surface updates together.
 *
 * The builders take optional values: the docs call them with no args
 * and get readable placeholders; the setup page passes the real agent
 * id / minted key so the snippet is copy-paste ready.
 *
 * Pure functions only — no React. Safe to import from Server or Client
 * Components.
 */

export const API_BASE = "https://api.metalins.ai/v1";

/** Shown when the real value isn't available (docs, or before a key is minted). */
export const KEY_PLACEHOLDER = "YOUR_METALINS_KEY";
export const AGENT_SECRET_PLACEHOLDER = "YOUR_AGENT_SECRET";

/** Install line — its own block because it's shell, not Python. */
export const PIP_INSTALL = "pip install metalins-drift";

interface RegisterOpts {
  apiKey?: string;
  name?: string;
}

/**
 * SDK quickstart: register a NEW agent (first run) and resume it on
 * later runs. Used by the docs quickstart + the HTTP API reference.
 */
export function sdkRegisterSnippet(opts: RegisterOpts = {}): string {
  const apiKey = opts.apiKey ?? KEY_PLACEHOLDER;
  const name = opts.name ?? "my-agent";
  return `import metalins_drift

# First run registers the agent and stores its state; later runs
# resume the same agent. Already created it in the dashboard? Use
# metalins_drift.Agent.attach(api_key, agent_id, agent_secret) instead.
agent = metalins_drift.Agent(api_key="${apiKey}", name="${name}")
agent.start()  # answers verification checks in the background

# Wherever your agent finishes a turn — log() hashes locally, so raw
# prompt and response text never leave your process.
agent.log(input=user_message, output=agent_reply)

# Read status anytime; stop the loop on shutdown.
print(agent.get_status()["verification"])
agent.stop()`;
}

interface AttachOpts {
  apiKey?: string;
  agentId?: string;
  agentSecret?: string;
  /** When set, adds a `name=` line — the per-agent setup page passes the real name. */
  name?: string;
}

/**
 * SDK: attach to an agent that ALREADY exists (created in the
 * dashboard). Used by the in-dashboard setup page + the HTTP API
 * reference. `agent_secret` was shown once at creation (#931).
 */
export function sdkAttachSnippet(opts: AttachOpts = {}): string {
  const apiKey = opts.apiKey ?? KEY_PLACEHOLDER;
  const agentId = opts.agentId ?? "agt_...";
  const agentSecret = opts.agentSecret ?? AGENT_SECRET_PLACEHOLDER;
  const nameLine = opts.name ? `\n    name="${opts.name}",` : "";
  return `import metalins_drift

# Connect an agent that already exists (created in the dashboard).
# agent_secret was shown once when you created it.
agent = metalins_drift.Agent.attach(
    api_key="${apiKey}",
    agent_id="${agentId}",
    agent_secret="${agentSecret}",${nameLine}
)
agent.start()  # answers verification checks in the background

# Wherever your agent finishes a turn — log() hashes locally, so raw
# prompt and response text never leave your process.
agent.log(input=user_message, output=agent_reply)

agent.stop()  # on shutdown`;
}

interface EventCurlOpts {
  apiKey?: string;
  agentId?: string;
}

/**
 * Raw HTTP: log one event with curl — the any-language path. On its
 * own this covers event reporting; answering verification checks from
 * another language means implementing the check round-trip.
 */
export function eventCurlSnippet(opts: EventCurlOpts = {}): string {
  const apiKey = opts.apiKey ?? KEY_PLACEHOLDER;
  const agentId = opts.agentId ?? "agt_...";
  return `curl -X POST ${API_BASE}/agents/${agentId}/events \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "input_hash":  "<sha256 hex of the user input>",
    "output_hash": "<sha256 hex of the agent output>"
  }'`;
}
