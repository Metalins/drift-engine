/**
 * /agents/new — register a new agent.
 *
 * History: this used to be a multi-step wizard. The original second step
 * asked "how variable are its answers?" to capture an `agent_profile`
 * that selected which protections applied. As of gh-77 the engine
 * auto-detects behavior mode server-side from the first ~20 events, so
 * the declared profile no longer gates anything and asking for it was
 * pure friction (Jose: "complejidad innecesaria para Diana", gh-78).
 *
 * With the profile step gone there is only one thing to ask — the name
 * (plus optional description/model/framework) — so the wizard collapses
 * to a single screen. Creation happens here so <CreateAgentForm> can
 * surface the one-time agent_secret (#931) right before /connect.
 */
import Link from "next/link";
import { ApiError, registerAgent } from "@/lib/api";
import { WizardProgress } from "@/components/WizardProgress";
import { CreateAgentForm, type CreateAgentState } from "./CreateAgentForm";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Connect a new agent",
};

// ---------- Server action (final submit) --------------------------------- //

/**
 * #931 — the action returns the freshly-minted `agent_secret` so
 * <CreateAgentForm> can surface it once before the customer continues to
 * /connect. The secret stays in React state on the client — it is never
 * put in the URL.
 *
 * gh-78: no `agent_profile` is collected or sent. The engine detects
 * behavior mode itself (gh-77); any profile a caller posts is ignored
 * server-side.
 */
async function createAgentAction(
  _prev: CreateAgentState,
  formData: FormData,
): Promise<CreateAgentState> {
  "use server";
  const name = String(formData.get("name") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const model = String(formData.get("model") ?? "").trim();
  const framework = String(formData.get("framework") ?? "").trim();

  // Defense in depth: the form requires a name, but someone could POST
  // the action directly.
  if (!name) {
    return {
      status: "error",
      message: "The agent needs a name.",
    };
  }

  const metadata: Record<string, unknown> = {};
  if (description) metadata.description = description;

  try {
    const res = await registerAgent({
      name,
      model: model || undefined,
      framework: framework || undefined,
      metadata,
    });
    return {
      status: "created",
      agentId: res.agent_id,
      agentSecret: res.agent_secret,
    };
  } catch (e) {
    let msg: string;
    if (e instanceof ApiError) {
      msg =
        e.status === 409
          ? "An agent with that name already exists — pick another."
          : e.status === 401 || e.status === 403
            ? "Your session expired — please sign in again."
            : `Couldn't create the agent (${e.status}). Try again, or contact support if it persists.`;
    } else {
      msg =
        "Couldn't create the agent. Try again, or contact support if it persists.";
    }
    return { status: "error", message: msg };
  }
}

// ---------- Page --------------------------------------------------------- //

export default async function NewAgentPage({
  searchParams,
}: {
  searchParams: Promise<{
    name?: string;
    description?: string;
    model?: string;
    framework?: string;
    error?: string;
  }>;
}) {
  const sp = await searchParams;

  // Prefills are still honored if something links in with values in the
  // URL (e.g. a retry after an error), but the flow is a single step now.
  const namePrefill = sp.name ?? "";
  const descriptionPrefill = sp.description ?? "";
  const modelPrefill = sp.model ?? "";
  const frameworkPrefill = sp.framework ?? "";

  return (
    <main className="mx-auto max-w-xl space-y-6">
      <div>
        <Link
          href="/dashboard"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to agents
        </Link>
        <div className="mt-3">
          <WizardProgress currentStep={1} />
        </div>
      </div>

      {sp.error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {decodeURIComponent(sp.error)}
        </div>
      )}

      <CreateAgentForm
        namePrefill={namePrefill}
        descriptionPrefill={descriptionPrefill}
        modelPrefill={modelPrefill}
        frameworkPrefill={frameworkPrefill}
        action={createAgentAction}
      />
    </main>
  );
}
