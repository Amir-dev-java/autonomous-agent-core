# Local Coding Agent Roadmap

This roadmap builds on the current Python, Ollama, isolated-worktree workflow. The guiding goals are reliable code changes, measurable answer quality, low token use, and local-first operation. Each stage should have acceptance criteria before the next layer is added.

## Current baseline

- Local Ollama planner, implementation, and review roles.
- Isolated Git worktree per task, bounded test runner, review, and explicit publishing.
- SQLite task history and lexical BM25 RAG with incremental source indexing.
- Retrieval coverage is reported, but this is not yet a semantic relevance evaluator.

## Planned stages

### 1. Measure and improve retrieval

- Keep BM25 as a no-extra-service fallback.
- Add PostgreSQL with `pgvector` as the persistent vector store when a local PostgreSQL service is available.
- Generate embeddings through a configurable local Ollama embedding model; never silently send source code to a remote embedding API.
- Store repository, revision, path, chunk boundaries, content hash, and embedding model/version with each vector. Incrementally re-embed changed chunks and remove stale chunks.
- Use hybrid retrieval (BM25 plus vector similarity), repository and file filters, deduplication, and a strict context token budget.
- Evaluate with a small versioned set of repository questions and relevant-file labels. Track Recall@k, MRR/nDCG, query coverage, retrieval latency, and prompt token count. Compare changes against the BM25 baseline.

### 2. Independent evaluator

- Add an evaluator role separate from the planner, implementer, and reviewer.
- Compare the user request against observable code changes, test results, and review evidence; require evidence for each acceptance criterion.
- Start with deterministic checks, then optionally add a local-model judge. Calibrate it against reviewed examples and track false acceptance and false rejection rates.
- Keep evaluation advisory until its reliability is measured; it must not bypass tests, review, path restrictions, or explicit publishing.

### 3. Token and prompt efficiency

- Record Ollama prompt/evaluation token counts and latency per role when the local server returns usage metadata.
- Set explicit context budgets by role. Send retrieved excerpts and concise file/path metadata instead of repeatedly sending the whole repository snapshot.
- Avoid duplicating the objective, source context, and previous role output across prompts; pass typed, compact handoffs between roles.
- Use model-aware token counting when available, with a conservative fallback estimate. Never treat a character limit as an exact token limit.
- Measure tokens per successful task, retries, latency, and acceptance rate. Require evaluator quality to stay stable or improve as token use falls.

### 4. Durable task queue and workers

- Change intake to persist a queued task and return immediately.
- Add worker leases, bounded retries, cancellation, per-repository concurrency limits, and recovery after process restart.
- Expose stage progress to the dashboard without holding the HTTP request open.
- Tune worker count against actual GPU/VRAM usage and queue latency; multiple roles should share one local model service where possible.

### 5. MCP integration

- Add an MCP client for explicitly configured local tools the agent needs.
- Offer a separate MCP server only for a narrow, allowlisted set of project operations.
- Validate tool arguments and results, enforce per-tool permissions and timeouts, and record every invocation. No unrestricted shell or filesystem tool by default.

### 6. Git delivery and operations

- Keep task branches isolated and publishing explicit.
- Add pull-request creation only after branch, test, review, and evaluator evidence are visible to the user.
- Add health checks, structured logs, backup/retention policy for task and vector data, and operational recovery guidance.

## Constraints and decision gates

- Local inference and embeddings are the default. Any remote provider must be an explicit user-configured option with clear data-flow boundaries.
- Do not introduce PostgreSQL, Redis, vLLM, or additional model downloads until the stage needs them and the machine can run them. pgvector is a planned vector-store target, not a current runtime dependency.
- Keep small interfaces around model providers, vector stores, and workers so each can be replaced without rewriting workflow policy.
- Optimize for measured task success and token cost together; a shorter prompt that lowers correctness is a regression.
