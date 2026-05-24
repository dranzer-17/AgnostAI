# Agnost Signals — Reasoning & Design Decisions

## What Was Built

A real-time voice analytics engine that ingests VAPI end-of-call webhooks, extracts the user's core problem using an LLM, clusters it by intent, runs sentiment analysis, and surfaces the results on a PM dashboard.

**Live — try it:**
- Dashboard: https://agnost-ai.vercel.app
- Backend API: `https://agnost-backend-37579330977.us-central1.run.app`
- **VAPI Phone Number: +1 (319) 719-9242** — call this number, describe an issue with an AI agent, and watch the cluster appear on the dashboard in real time

---

## Current Architecture: Agentic + Redis (What Shipped)

### Why This Approach

Given a weekend, the priority was: get real data flowing end-to-end fast, with a pipeline that actually works on the first call. HDBSCAN requires a corpus of embeddings before it produces meaningful clusters — it can't cluster a single conversation. The agentic approach produces a named, described cluster on the very first call.

### End-to-End Flow

```
VAPI Call Ends
      │
      ▼
POST /api/vapi/webhook
      │
      ├─ Verify x-vapi-secret header
      │
      ├─ Redis SET processed:{call_id} NX EX 86400
      │     └─ duplicate? → return early
      │
      ▼
Summarization Agent (Groq llama-3.3-70b)
  "Extract exact feature + error behavior from transcript"
      │
      ▼
  clean_issue: "email sending agent throws address-not-found
                error when forming recipient address"
      │
      ├──────────────────────────────┐
      ▼                              ▼
Sentiment Agent                Clustering Agent
(Groq llama-3.3-70b)          (Groq llama-3.3-70b + tool_choice)
POSITIVE / NEGATIVE / NEUTRAL   tools: assign_to_cluster
                                        create_new_cluster
      │                              │
      └──────────────┬───────────────┘
                     ▼
           Neon Postgres Write
           ┌─────────────────────────────┐
           │ conversations               │
           │ clusters (upsert)           │
           │ cluster_members             │
           │ insights (aggregated stats) │
           └─────────────────────────────┘
                     │
                     ▼
           Dashboard reads /api/insights
```

### The Multi-Agent Design

Instead of one monolithic LLM call, three specialized agents run in a pipeline:

```
Orchestrator (run_pipeline)
      │
      ├─ Step 1: Summarization Agent
      │    Input:  raw transcript or summary
      │    Output: clean_issue (1-2 sentences, feature + error)
      │    Why:    strips agent boilerplate, forces specificity
      │
      └─ Step 2 (parallel via asyncio.gather):
           ├─ Sentiment Agent → { label: NEGATIVE }
           └─ Clustering Agent → tool call: create_new_cluster
                                  { label: "Email Sending Error",
                                    description: "..." }
```

Parallelism via `asyncio.gather` cuts latency — sentiment and clustering run simultaneously rather than sequentially.

### Why Tool Calls for Clustering

The clustering agent uses `tool_choice="required"` with two tools: `assign_to_cluster` and `create_new_cluster`. This forces the LLM to return structured JSON rather than freeform text, eliminating parsing hacks. The tool definitions carry the schema constraints (label max words, description requirements) directly to the model.

### Why Redis for Dedup (Not DB)

VAPI occasionally fires duplicate `end-of-call-report` webhooks. A `UNIQUE` constraint on `vapi_call_id` in Postgres would work, but it requires a DB round-trip before processing. Redis `SET NX` is O(1) and rejects duplicates before any LLM call happens — saving ~3 Groq API calls per duplicate.

### Why Groq Over Local Models

| Option | Latency | Cost | Cold Start |
|---|---|---|---|
| Groq (llama-3.3-70b) | ~800ms | ~$0.001/call | None |
| HuggingFace RoBERTa (local) | 200ms first call | Free | 30s+ model load |
| OpenAI GPT-4o | ~1.5s | ~$0.01/call | None |

RoBERTa was the original sentiment model. Replaced because: 500MB model loaded into memory on every cold start, torch pulled in 2GB of dependencies, and Python 3.12 had PyO3/pydantic-core incompatibility issues. Groq on llama-3.3-70b is faster end-to-end, cheaper at this scale, and runs three tasks instead of one.

### Why Neon Postgres (Not Pure Redis or Mongo)

Insights require aggregations across conversations — `AVG(frustration)`, `COUNT(*)` per cluster, `SUM(resolved)`. These are SQL operations. Postgres handles relational + analytical queries in one place. Neon specifically: serverless, zero-config SSL, works with asyncpg out of the box.

MongoDB was considered but rejected — the schema is relational (conversations → cluster_members → clusters), and document store gains nothing here.

### Alternatives Rejected

| Alternative | Why Rejected |
|---|---|
| Cosine similarity threshold (no LLM) | Misses semantic intent — "can't log in" and "password reset loop" are different problems, close in embedding space |
| Single LLM call (sentiment + clustering together) | Mixing tasks degrades output quality; harder to debug which agent failed |
| Synchronous sequential pipeline | Adds ~800ms per call for no reason — sentiment and clustering are independent |
| Pinecone for vector store | Adds a third paid service; pgvector on Neon handles < 1M vectors with HNSW index fine |

---

## What I'd Build With a Month: Approach 2 — Embeddings + HDBSCAN

The agentic approach has one fundamental weakness: **LLM drift**. If the clustering agent's prompt is slightly off, semantically identical problems get split into different clusters. At 10k+ conversations, you end up with 400 clusters where 40 is the right number.

The fix is to ground clustering in geometry, not language.

### Architecture

```
Ingest Path (real-time, unchanged):
  VAPI webhook → summarization agent → clean_issue → store in Postgres

Embedding Pipeline (async, per conversation):
  clean_issue
      │
      ▼
  all-MiniLM-L6-v2 (384-dim sentence embedding)
      │
      ▼
  pgvector (HNSW index, cosine distance)

Nightly Batch Job (2am):
      │
      ▼
  Pull all embeddings (last 30 days)
      │
      ▼
  UMAP (384-dim → 10-dim)
  Why: HDBSCAN degrades in high dimensions (curse of dimensionality)
  UMAP preserves local + global structure, removes noise dimensions
      │
      ▼
  HDBSCAN (min_cluster_size=5, min_samples=3)
  Why: no K needed, discovers unknown shapes,
       labels noise points as -1 (doesn't force bad assignments)
      │
      ▼
  Per-cluster: KeyBERT label extraction
               TF-IDF discriminative terms
               Sentiment aggregation
      │
      ▼
  Write clusters + insights tables
  Invalidate Redis dashboard cache
```

### UMAP + HDBSCAN Diagram

```
Raw embeddings (384-dim)          After UMAP (10-dim)
  ·  · ·   ·    ·                   ●●●
·    ·   ·    ·    ·               ●   ●      ▲▲
  ·  ·  ·   ·   ·    ·            ●     ●   ▲  ▲▲
·   ·    ·    ·   ·               ●●●●●●●  ▲▲▲▲▲
  ·   ·    ·                                        ■ ■
                                  HDBSCAN finds      ■■■
                                  dense regions,     ■ ■
                                  ignores noise (·)
```

### Hybrid: LLM + HDBSCAN

Don't pick one. Use both:

```
Real-time path:  LLM clustering → immediate cluster assignment (users see results now)
Weekly batch:    HDBSCAN → correctness pass
                   - merges LLM-fragmented clusters
                   - splits LLM-merged clusters
                   - rebuilds centroids from ground truth
```

The LLM assigns new conversations instantly. HDBSCAN runs weekly to fix accumulated drift. A merge job reconciles them: if HDBSCAN says clusters A and B are the same region → merge, reassign members, update centroids.

### What Else Would Change

**Frustration Index**: Currently rule-based (repeated keywords, call duration, ended_reason). With a month: fine-tune a small classifier on labeled calls. The signal is richer in audio features (pace, pauses, tone) — would explore Whisper transcripts with timestamps to detect hesitation patterns.

**Multi-tenancy**: Every table gets `org_id`. Row-Level Security in Postgres means one DB, safe isolation. Can't retrofit this — would be Day 1.

**Embedding drift**: MiniLM embeddings from 6 months ago may not cluster correctly with today's. Track `model_version` on embeddings, re-embed on model update.

**Streaming**: VAPI sends the transcript in real-time chunks (not just end-of-call). With a month, would process the stream mid-call to detect frustration spikes early and alert the agent live.

**Dashboard**: Auto-refresh via SSE or WebSocket instead of manual refresh button. Trend lines (volume per cluster over 7 days). Anomaly alerts ("Login errors up 3x in last hour").

---

## Stack Summary

| Layer | Weekend (Shipped) | Month (Would Build) |
|---|---|---|
| Clustering | Groq LLM (agentic) | LLM real-time + HDBSCAN weekly |
| Embeddings | None | all-MiniLM-L6-v2 + pgvector HNSW |
| Sentiment | Groq llama-3.3-70b | Same + confidence score |
| Frustration | Rule-based heuristic | Fine-tuned classifier |
| Dedup | Redis SET NX | Same |
| DB | Neon Postgres | Same + org_id RLS |
| Infra | Cloud Run + Vercel | Same + Vercel Queues for async embedding |
| Dashboard | Static refresh | SSE live updates + trend charts |
