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
- Python 3.10+

### 1. Clone and configure

```bash
git clone https://github.com/Metalins/drift-engine
cd drift-engine
cp .env.example .env
# Edit .env with your settings
```

### 2. Generate signing keys

Drift Engine issues κ-Proofs signed with an RSA key pair. You must generate your own — do not share the private key.

```bash
mkdir -p server/keys
openssl genrsa -out server/keys/private_key.pem 2048
openssl rsa -in server/keys/private_key.pem -pubout -out server/keys/public_key.pem
```

Update `.env` to point to these paths:
```env
PRIVATE_KEY_PATH=./keys/private_key.pem
PUBLIC_KEY_PATH=./keys/public_key.pem
```

### 3. Start the server

```bash
docker compose up --build
```

The API is now available at `http://localhost:8000`. Check the health endpoint:

```bash
curl http://localhost:8000/health
```

API docs: `http://localhost:8000/docs`

## SDK

Use the Python SDK to instrument your agents:

```bash
pip install metalins-drift
```

→ [drift-engine-python](https://github.com/Metalins/drift-engine-python)

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

Metalins is an independent research lab building novel tools through open research.

→ [metalins.com](https://metalins.com)  
→ [github.com/Metalins](https://github.com/Metalins)

## License

AGPL-3.0. If you modify and deploy this as a service, you must release your modifications under the same license.

Copyright (C) 2026 Jose Miguel Hernandez Perez
