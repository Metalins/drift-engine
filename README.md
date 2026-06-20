# Metalins Drift Engine

**Open-source behavioral fingerprinting for continuous identity verification of AI agents.**

Drift Engine detects model substitution, prompt injection, and behavioral drift in production LLM agents — without accessing model weights, raw prompts, or raw responses.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20693202.svg)](https://doi.org/10.5281/zenodo.20693202)

## How it works

The SDK logs structural features of each agent turn (output length, format markers, tool calls, latency) client-side. The engine builds a per-agent behavioral baseline from organic traffic and runs windowed two-sample tests (Kolmogorov–Smirnov, Wasserstein, chi-squared) to detect when the agent's distributional signature changes.

Verdicts are issued as **κ-Proofs** — signed JSON Web Tokens verifiable by any third party against a public JWKS endpoint.

Read the paper: [κ-Identity: Behavioral Fingerprinting for Continuous Verification of LLM Agents](https://zenodo.org/records/20693203) — DOI: 10.5281/zenodo.20693202

## Self-hosting

### Requirements

- Docker and Docker Compose

That's it. Everything else is handled on first boot.

### Start

```bash
git clone https://github.com/Metalins/drift-engine
cd drift-engine
docker compose up
```

On first boot the server will:
1. Generate an RSA signing keypair (persisted in a Docker volume — never leaves your machine)
2. Initialize the database schema
3. Create an admin account (`admin@localhost` / `changeme`) — **change this on first login**
4. Print a dev API key in the logs — save it, it's shown only once

```
✓ Dev API key created. SAVE THIS — it is only shown once:

   ml_dev_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

Use it as: Authorization: Bearer <api_key>
```

The API is now available at `http://localhost:8000`.

```bash
# Verify it's running
curl http://localhost:8000/health
# → {"status":"ok","service":"metalins-server"}

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@localhost","password":"changeme"}'

# List agents (use the API key from the logs)
curl http://localhost:8000/internal/v1/agents \
  -H "Authorization: Bearer ml_dev_XXXX..."
```

**Interactive API docs:** `http://localhost:8000/docs`

### Configuration (optional)

Copy `.env.example` to `.env` to customize ports, log level, and other settings. The defaults work out of the box.

### Stopping

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and wipe all data
```

## SDK

Instrument your agents with the Python SDK:

```bash
pip install metalins-drift
```

```python
from metalins_drift import MetalinsClient

client = MetalinsClient(
    api_key="ml_dev_XXXX...",
    server_url="http://localhost:8000",  # your self-hosted instance
)

# Register an agent
agent = client.register_agent(name="my-agent")

# Log turns
client.log_turn(agent_id=agent["id"], input="...", output="...")
```

→ [drift-engine-python](https://github.com/Metalins/drift-engine-python) for full SDK docs.

## Architecture

```
Agent (your code)
  └── metalins-drift SDK     # computes features client-side, logs to server
        └── Drift Engine     # stores events, builds baseline, runs κ-engine
              └── κ-Proof    # signed JWT, verifiable by any third party
```

## Research

This implementation is the reference system for the κ-Identity framework described in:

> Hernandez, J. M. (2026). *κ-Identity: Behavioral Fingerprinting for Continuous Verification of LLM Agents.* Metalins. DOI: [10.5281/zenodo.20693202](https://doi.org/10.5281/zenodo.20693202)

## Organization

Metalins is an independent research lab.

→ [metalins.com](https://metalins.com)  
→ [github.com/Metalins](https://github.com/Metalins)

## License

AGPL-3.0. If you modify and deploy this as a service, you must release your modifications under the same license.

Copyright (C) 2026 Jose Miguel Hernandez Perez
