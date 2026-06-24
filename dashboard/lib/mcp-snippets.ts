/**
 * Shared MCP snippet/config helpers — extracted from McpQuickStart in
 * Sprint UX-5.15.T so both the dense `/agents/[id]/mcp` page and the
 * step-by-step `/agents/[id]/mcp/setup` wizard read from the same
 * source of truth. Edit the server name format, MCP URL, or snippet
 * shape here and both surfaces update together.
 *
 * Pure functions only — no React. Safe to import from Server or
 * Client Components.
 */

export const MCP_BASE = "https://api.metalins.ai/v1/mcp";
export const MCP_URL = `${MCP_BASE}/jsonrpc`;
export const PLACEHOLDER = "YOUR_API_KEY";

/**
 * Turn an agent name into a safe MCP server name for the client config.
 *
 * Sprint UX-5.15.M follow-up: the previous snippet always used
 * `metalins` as the server name, so `claude mcp add ...` exploded
 * with "MCP server metalins already exists in user config" the moment
 * a customer had a second agent. We now scope by agent so each
 * registration gets its own entry.
 *
 *   "mi-claude-desktop" → "metalins-mi-claude-desktop"
 *   "Agente Jose 2"     → "metalins-agente-jose-2"
 *
 * Claude Code's MCP-name validator accepts kebab-case (lowercase
 * letters, digits, hyphens). We normalize to that.
 */
export function mcpServerName(agentName: string): string {
  const slug = agentName
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-+/g, "-")
    .slice(0, 40);
  return slug ? `metalins-${slug}` : "metalins";
}

/**
 * Build the client config snippets given a key value. When the user
 * hasn't minted (or has explicitly hidden) a key, we render the
 * placeholder so the shape is still visible for orientation.
 *
 * Per-client notes (UX-5.15.L — verified against each vendor's
 * official docs after Jose flagged the prior snippets):
 *
 *   - Claude Code (CLI): the URL is POSITIONAL. The `--url` flag does
 *     not exist (CLI errors with "unknown option '--url'"). `-H` is
 *     short for `--header`. `--scope user` makes the entry available
 *     across every Claude Code project on this machine.
 *
 *   - Cursor: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json`
 *     (project). HTTP transport is recognized when `url` + optional
 *     `headers` are present in the mcpServers entry.
 *
 *   - Claude Desktop: NOT supported via `claude_desktop_config.json`.
 *     That file is stdio-only. Remote HTTP MCP servers are added
 *     through Settings → Connectors → Add custom connector. The UI
 *     renders the explicit steps instead of a JSON block that would
 *     silently fail to connect.
 */
export interface ClientConfigSnippets {
  claudeCode: string;
  cursor: string;
}

export function buildClientConfigSnippets(
  key: string,
  serverName: string,
): ClientConfigSnippets {
  const claudeCode = `claude mcp add --transport http ${serverName} ${MCP_URL} \\
  -H "Authorization: Bearer ${key}" \\
  --scope user`;

  const cursor = `{
  "mcpServers": {
    "${serverName}": {
      "url": "${MCP_URL}",
      "headers": {
        "Authorization": "Bearer ${key}"
      }
    }
  }
}`;

  return { claudeCode, cursor };
}

/**
 * Build the persistent system-prompt snippet (D-PROD.26 / UX-5.15.X /
 * UX-5.15.Y).
 *
 * Goes into CLAUDE.md / .cursor/rules / Claude Desktop profile /
 * ChatGPT Custom Instructions. The model sees this on every turn, so
 * we keep it short and structured around the *action*, not the brand
 * story. Framed as a legitimate verification layer the user installed,
 * NOT covert surveillance: when the user asks "what's
 * metalins_log_event?" the model should explain openly.
 *
 * Anti-receta (D-PROD.25): we never tell the model what β expects.
 * Inputs are just hashes of in/out; the model has no visibility into
 * the engine's behavior-shape model.
 *
 * Why the UX-5.15.Y rewrite — observed failure mode (Jose's Claude
 * Code session): the model didn't log the first turn, didn't log
 * short replies ("that's a fun thought, but..."), and only kicked in
 * once the user explicitly asked "ya mandaste el evento?". Root
 * causes in the old wording:
 *   1. The directive came AFTER a paragraph of brand context, so the
 *      model treated logging as background flavor, not contract.
 *   2. "after each meaningful turn" gave the model an escape hatch —
 *      it judged a short refusal as not-meaningful.
 *   3. "You don't need to narrate each call. Treat it like background
 *      plumbing" trained the model to deprioritize the call itself,
 *      not just the narration.
 *
 * New approach: action first; "BEFORE finishing any reply" instead of
 * "after each turn" (pre-hook beats post-hook); enumerate the edge
 * cases the model typically skips (first acknowledgement, one-word
 * answers, refusals, tool-only turns); state the consequence ("a
 * skipped turn breaks the chain"); push brand context to a footnote
 * at the end.
 */
export function buildSystemPromptSnippet(
  agentId: string,
  serverName: string,
): string {
  return `# Metalins logging — applies to every reply in this conversation

BEFORE you finish ANY reply (including the very first acknowledgement,
one-word answers, refusals, and tool-only turns), do this:

  1. Compute input_hash  = SHA-256 hex of the user's message that
     prompted the turn.
  2. Compute output_hash = SHA-256 hex of the reply you are about to
     send.
  3. Call the \`metalins_log_event\` tool on the \`${serverName}\` MCP
     server with:
        agent_id:    "${agentId}"
        input_hash:  <from step 1>
        output_hash: <from step 2>
  4. Then send the reply.

No exceptions. A skipped turn breaks the chain and invalidates the
conversation's verification record. If you decline a request, log the
decline. If you answer "yes", log it. If you only ran tools, log the
turn anyway.

Use any SHA-256 utility you have: bash (\`echo -n "text" | sha256sum\`),
code execution, an inline hash function — your choice.

Don't narrate the calls unless the user asks; it's background logging.
If a call errors, surface the error briefly and keep working.

---
Why this exists: this account uses Metalins, an identity-verification
layer for AI assistants. The per-turn log produces a tamper-evident
record so the user can later prove this agent's behavior is the one
they set up — not a clone, not swapped, not drifted. The user
installed Metalins deliberately and only the hashes leave this
session (never message contents).`;
}

/**
 * Build the per-conversation primer snippet (UX-5.15.X / UX-5.15.Y).
 *
 * Use case: clients without a usable persistent-instructions slot
 * (free ChatGPT, plain Claude.ai chat without a Project, anyone who
 * doesn't want to commit a CLAUDE.md). The customer pastes this as
 * their FIRST message in each new conversation.
 *
 * UX-5.15.Y rewrite (see buildSystemPromptSnippet docs for the
 * observed failure mode): same fix — action first, brand context
 * last, "BEFORE finishing any reply" instead of "after each turn",
 * explicit edge cases, hard consequence on skip. The primer keeps a
 * slightly warmer opener (the user is greeting the model) and a
 * privacy line about hashes-only, since this is read by the model
 * once per chat instead of every turn — a few extra lines of context
 * up top are worth it.
 */
export function buildConversationPrimerSnippet(
  agentId: string,
  serverName: string,
): string {
  return `Hi. Before we start: this conversation is instrumented with
Metalins, and I need you to follow one rule for the entire chat.

**The rule.** BEFORE you finish ANY reply (including this very first
acknowledgement, one-word answers, refusals, and tool-only turns), do
this:

  1. Compute input_hash  = SHA-256 hex of my message that prompted
     the turn.
  2. Compute output_hash = SHA-256 hex of the reply you are about to
     send.
  3. Call the \`metalins_log_event\` tool on the \`${serverName}\` MCP
     server with:
        agent_id:    "${agentId}"
        input_hash:  <from step 1>
        output_hash: <from step 2>
  4. Then send the reply.

No exceptions. A skipped turn breaks the chain and invalidates this
conversation's verification record. If you decline a request, log
the decline. If you answer "yes", log it. If you only ran tools, log
the turn anyway.

Use any SHA-256 utility you have: bash (\`echo -n "text" |
sha256sum\`), code execution, an inline hash function — your choice.

A few notes so you cooperate confidently:
  - This is not covert. I installed Metalins deliberately and pasted
    these instructions; you can answer openly if I ask what
    \`metalins_log_event\` is doing.
  - Don't narrate every call mid-flow — treat it like background
    logging. Just call it before each reply.
  - If a call errors, mention it briefly and keep working. Don't
    drop the conversation.
  - Metalins receives only the hashes, never the message contents.
    That's the privacy promise.

Now here's what I actually wanted to ask you:`;
}
