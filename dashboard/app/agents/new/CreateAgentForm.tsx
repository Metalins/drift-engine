"use client";

/**
 * CreateAgentForm — gh-78 (remove behavior-profile selector).
 *
 * The /agents/new flow used to be a two-step wizard whose entire second
 * step existed to ask "how variable are its answers?" and capture an
 * `agent_profile`. As of gh-77 the engine auto-detects behavior mode
 * server-side from the first ~20 events — the declared profile no longer
 * gates any protection, so asking the customer for it was pure friction
 * (Jose: "complejidad innecesaria para Diana"). Diana only names the
 * agent; everything else is optional.
 *
 * So this is now a single screen: agent name (required) + an optional
 * details disclosure (description / model / framework), and the submit.
 *
 * Creation lives here because the server action returns the freshly
 * minted agent_secret (#931) and we surface it once via <SecretReveal>
 * before the customer continues. The secret only ever lives in React
 * state here — never in the URL — so a client component driven by
 * useActionState is the right shape.
 */
import { useActionState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { SecretReveal } from "@/components/agents/SecretReveal";

export type CreateAgentState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "created"; agentId: string; agentSecret: string };

export function CreateAgentForm({
  namePrefill,
  descriptionPrefill,
  modelPrefill,
  frameworkPrefill,
  action,
}: {
  namePrefill: string;
  descriptionPrefill: string;
  modelPrefill: string;
  frameworkPrefill: string;
  action: (
    prev: CreateAgentState,
    formData: FormData,
  ) => Promise<CreateAgentState>;
}) {
  const [state, formAction, pending] = useActionState<
    CreateAgentState,
    FormData
  >(action, { status: "idle" });

  // ---- Success: surface the one-time secret ----------------------------- //
  if (state.status === "created") {
    return (
      <section className="space-y-5">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Agent created.
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Save the secret below before you continue. You need it to
            connect your agent via the SDK or HTTP API.
          </p>
        </div>
        <SecretReveal secret={state.agentSecret} />
        <div className="flex justify-end">
          <Link
            href={`/agents/${encodeURIComponent(state.agentId)}/api/setup?new=1`}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Continue to connect
            <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    );
  }

  // ---- Form ------------------------------------------------------------- //
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">
        Name your agent.
      </h1>
      <p className="text-sm text-muted-foreground">
        Just so you can find it later. Everything else is optional —
        Drift Engine watches how your agent actually behaves and turns on the
        right protections automatically.
      </p>

      {state.status === "error" && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {state.message}
        </div>
      )}

      <form action={formAction} className="space-y-5">
        <label className="block text-sm font-medium">
          Agent name
          <input
            name="name"
            required
            minLength={1}
            maxLength={120}
            defaultValue={namePrefill}
            autoFocus
            placeholder="e.g. mi-claude-desktop"
            className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>

        <details className="rounded-md border bg-card/40 p-3">
          <summary className="cursor-pointer text-sm font-medium hover:text-foreground">
            Add optional details (description, model, framework)
          </summary>
          <div className="mt-3 space-y-4">
            <label className="block text-sm font-medium">
              Description
              <textarea
                name="description"
                rows={3}
                maxLength={400}
                defaultValue={descriptionPrefill}
                placeholder="What does this agent do?"
                className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm font-medium">
                Model
                <input
                  name="model"
                  defaultValue={modelPrefill}
                  placeholder="claude-sonnet-4-6, gpt-5, etc."
                  className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
              <label className="block text-sm font-medium">
                Framework
                <input
                  name="framework"
                  defaultValue={frameworkPrefill}
                  placeholder="langchain / openai-sdk / custom"
                  className="mt-1 block w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
            </div>
          </div>
        </details>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={pending}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {pending ? "Creating…" : "Create agent"}
          </button>
        </div>
      </form>
    </>
  );
}
