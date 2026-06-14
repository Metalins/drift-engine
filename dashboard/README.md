# Metalins dashboard

Next.js 16 + React 19 dashboard for the Metalins AIP (Agent Identity Protocol)
authority. Server Components + Server Actions + Supabase magic-link auth,
deployed to Cloudflare Workers via `@opennextjs/cloudflare`.

**Production:** [`metalins-dashboard.josemiguelhernandez-es.workers.dev`](https://metalins-dashboard.josemiguelhernandez-es.workers.dev)
(anti-indexed during alpha; flip `NEXT_PUBLIC_ALLOW_INDEX=true` on launch day.)

---

## Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Framework | Next.js 16.2.6 (App Router) | Server Components, Server Actions, async `params`/`searchParams`/`cookies` |
| UI | React 19 + Tailwind + shadcn primitives (inlined) | No external CSS framework needed; primitives are 30-line MIT snippets |
| Auth | Supabase Auth (magic-link, ES256 JWT) via `@supabase/ssr` | Stateless JWT validation on the backend, no roundtrip per request |
| Charts | Recharts | Identity score timelines |
| Icons | lucide-react | Tree-shakeable |
| Deploy | Cloudflare Workers + `@opennextjs/cloudflare` 1.19.9 | OpenNext is Cloudflare's official 2026+ adapter; replaces deprecated `@cloudflare/next-on-pages` |
| Dev | `next dev` (Turbopack) | Fast HMR |

---

## Local setup

```bash
cd dashboard
npm install
cp .env.local.example .env.local
# Edit .env.local — see "Environment variables" below
npm run dev
```

Open <http://localhost:3000>. The middleware will bounce you to `/login` if
you're not signed in. Use the magic-link form; Supabase will email you a
link that lands back on `/auth/callback` and creates your session cookie.

---

## Environment variables

All variables are public (prefixed `NEXT_PUBLIC_`) — they ship to the browser
because of how Supabase auth works. Secrets live on the backend (Cloud Run).

```env
# Metalins server (FastAPI on Cloud Run)
NEXT_PUBLIC_METALINS_API_URL=https://metalins-server-kluyinwahq-rj.a.run.app

# Supabase Auth — used by @supabase/ssr to validate sessions
NEXT_PUBLIC_SUPABASE_URL=https://ttxautbynuelvpbvengc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGci...   # from Supabase Project Settings → API

# Optional static API key fallback. Leave EMPTY in normal operation —
# magic-link login provides JWT auth. Only useful for headless scripts.
NEXT_PUBLIC_METALINS_API_KEY=

# Anti-indexation flag. false during alpha, true on launch day (D-PROD.16).
NEXT_PUBLIC_ALLOW_INDEX=false
```

For local dev, ensure Supabase Console → Authentication → URL Configuration
includes `http://localhost:3000/auth/callback` as a redirect URL.

---

## Scripts

```bash
npm run dev       # next dev (local development, Turbopack)
npm run build     # next build (raw Next.js build, NOT Cloudflare-ready)
npm run start     # next start (production-mode local server)
npm run lint      # next lint
npm run typecheck # tsc --noEmit
npm run preview   # opennextjs-cloudflare build + preview locally on workerd
npm run deploy    # opennextjs-cloudflare build + deploy to Cloudflare Workers
```

**Note:** `npm run deploy` requires `wrangler login` to have been run once.
In CI / Cloudflare Pages, this happens via the connected Git integration —
you don't need to authenticate manually.

---

## Deploy

Auto-deploy is wired via Cloudflare Workers + GitHub:

1. `git push origin main` to `Metalins/metalins`.
2. Cloudflare detects the push (its Git integration polls the repo).
3. Runs `cd dashboard && npm install && npm run deploy` in their build env.
4. Worker goes live at `metalins-dashboard.<account>.workers.dev`.

Manual deploy from your machine (rarely needed):

```bash
cd dashboard
npm run deploy
```

---

## Architecture

```
app/
├── layout.tsx                 # Root layout + AccountHeader (email + signout)
├── page.tsx                   # / → list of agents (Server Component)
├── not-found.tsx              # global 404
├── login/page.tsx             # Magic-link sign-in (Client Component)
├── auth/
│   ├── callback/route.ts      # OAuth code exchange after magic-link click
│   └── signout/route.ts       # POST → clear session cookies
├── agents/
│   ├── new/page.tsx           # Form to register an agent (Server Action)
│   └── [id]/
│       ├── page.tsx           # Detail: ConfidenceGauge + observables + probes
│       ├── not-found.tsx      # 404 for missing agent_id
│       └── keys/
│           ├── page.tsx       # List of keys scoped to this agent
│           └── KeyManager.tsx # Client component: create/revoke flow
└── api/
    ├── agents/[id]/api-keys/route.ts    # Proxy: POST create key
    └── api-keys/[id]/revoke/route.ts    # Proxy: POST revoke

components/
├── ui/                  # shadcn primitives (Card, Badge)
└── agents/              # Domain components: ConfidenceGauge, ObservableCard,
                         # EventsTable, MVSHistoryTimeline, PendingProbesPanel

lib/
├── api.ts               # Typed client for the Metalins server; forwards
│                        # Supabase session JWT as Bearer auth
├── utils.ts             # cn(), timeAgo(), formatPct(), formatObservable()
└── supabase/
    ├── client.ts        # Browser Supabase client (Client Components)
    └── server.ts        # Server Supabase client (Server Components)

middleware.ts            # Refreshes Supabase session cookies + auth gate
                         # (redirects to /login if no user, except public paths)
wrangler.jsonc           # Cloudflare Workers config
open-next.config.ts      # OpenNext adapter config
next.config.mjs          # Anti-indexation X-Robots-Tag header
```

---

## Auth flow

```
1. Visit /                         → middleware: no session cookie → redirect /login
2. /login → enter email             → Supabase emails a magic link
3. Click email link                 → /auth/callback?code=...
4. callback exchanges code          → session cookies (sb-access-token, sb-refresh-token)
5. Browser redirected to /          → middleware: session OK → renders agents list
6. Server Component fetches /v1/agents → uses session JWT as Bearer auth
7. Backend validates JWT via JWKS    → returns customer's agents
```

JWTs are ES256 (Supabase 2025+ default). The backend fetches Supabase's
public JWKS at `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` and caches it
for 1 hour. Legacy HS256 with `SUPABASE_JWT_SECRET` is supported as a
fallback for older Supabase projects.

---

## Anti-indexation (D-PROD.14 + D-PROD.16)

Three independent layers, all gated by `NEXT_PUBLIC_ALLOW_INDEX`:

| Layer | Mechanism | Source |
| --- | --- | --- |
| HTTP header | `X-Robots-Tag: noindex, nofollow` | `next.config.mjs` |
| Crawler manifest | `robots.txt: Disallow: /` | `app/robots.ts` |
| HTML meta | `<meta name="robots" content="noindex, nofollow, nocache">` | `app/layout.tsx` |

To go public:

```bash
# 1. Flip env var (Cloudflare dashboard → Workers → metalins-dashboard
#                  → Settings → Variables → Edit production)
NEXT_PUBLIC_ALLOW_INDEX=true

# 2. Trigger redeploy (Settings → Triggers → Redeploy)
```

---

## Troubleshooting

### "0 agents" after login, but I know I have agents

Your Supabase user's customer row exists but your API keys (created before
the Sprint 3a-auth migration) aren't linked. Run the backfill SQL in
`server/scripts/migrate-3a-auth.sql` (step 4) with your `auth.users.id`.

### "Invalid JWT: The specified alg value is not allowed"

The backend isn't deployed with the JWKS-aware version of `require_auth`.
Re-run `bash server/deploy-cloudrun.sh` after pulling latest server code.

### "Could not detect a directory containing static files" (Cloudflare build)

Your Cloudflare project was created as **Workers**, not Pages. Build
command should be `cd dashboard && npm install && npm run deploy` (notice
`deploy`, not just `build`).

### `npm ci` fails on Cloudflare build with lockfile errors

`package-lock.json` is out of sync with `package.json`. Re-run
`npm install` locally, commit the new lockfile, push.

---

## Related docs

- `docs/product/PRODUCT-SPEC.md` — product decisions (D-PROD.*)
- `docs/implementation/SPRINT-3-PLAN.md` — Sprint 3 plan + day-of-launch checklist
- `docs/operations/CLAUDE-INFRA-ACCESS.md` — what the AI agent can/can't do autonomously
