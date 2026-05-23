# Sentiment Analytics Engine — Architecture Approaches

## System Overview

A pipeline that ingests VAPI voice call transcripts via end-of-call webhooks, clusters emerging topics, and surfaces actionable insights for PMs.

**Input:** VAPI end-of-call webhook (call summary + transcript)  
**Output:** PM Dashboard — "20% of calls about refund delays", trending topics, sentiment per cluster

---

## Approach 1: Batch Clustering (HDBSCAN)

### How It Works
Conversations accumulate throughout the day. A nightly job processes all embeddings at once to find natural clusters.

```
VAPI webhook arrives
        ↓
Verify signature → Redis dedup (call_id) → embed summary (MiniLM) → store vector in Postgres
        ↓
Nightly cron job (2am):
  Pull all embeddings → UMAP dimensionality reduction → HDBSCAN clustering
        ↓
  KeyBERT labels per cluster → RoBERTa sentiment per cluster → write insights table
        ↓
PM Dashboard reads precomputed insights (Redis cache)
```

### Stack
| Component | Choice | Reason |
|---|---|---|
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) | Free, local, 384-dim, conversation-optimized |
| Dimensionality reduction | UMAP (10 components) | Removes noise from high-dim space before clustering |
| Clustering | HDBSCAN | No K needed, handles noise, variable density, discovers unknown topics |
| Labeling | TF-IDF + KeyBERT hybrid | Statistically discriminative + semantically meaningful |
| Sentiment | `cardiffnlp/twitter-roberta-base-sentiment-latest` | Contextual, understands "I've been waiting 2 weeks" as negative |
| Primary DB | Neon Postgres (pgvector, HNSW index) | Vector storage + relational metadata in one place |
| Queue / Dedup | Redis (Upstash) | O(1) dedup, async job queue, dashboard cache |

### Key Design Decisions

**Why VAPI summary, not full transcript:**
- Summary is already LLM-cleaned — no agent boilerplate noise
- Embeds more cleanly → tighter, more accurate clusters
- Fast enough (~50ms) to embed inline in webhook handler → no async queue needed for embedding

**Why `run_id` on cluster membership:**
- Clustering is non-deterministic — results shift between runs
- `run_id` lets you compare runs, roll back, A/B test parameters
- Dashboard always reads from `active_run_id` — zero downtime during recluster

**Why RoBERTa over VADER:**
- Already loading transformer models for embeddings — no extra overhead
- VADER misses contextual negativity ("I've been waiting 2 weeks" → VADER: neutral)
- Batch mode runs at 2am — speed irrelevant, accuracy matters

### Pros
- Globally optimal clusters — HDBSCAN sees ALL conversations simultaneously
- Automatically merges similar topics (no fragmentation)
- Fully deterministic and reproducible
- Zero API cost — runs entirely locally
- Scales to 1M+ conversations with nightly batch

### Cons
- Insights are stale until next morning
- New emerging topic takes up to 24h to surface
- Clusters rebuilt from scratch each run (mitigated by `run_id`)

---

## Approach 2: Dynamic LLM Clustering (Real-Time)

### How It Works
Each conversation is processed immediately on arrival. An LLM decides whether the conversation fits an existing cluster or warrants creating a new one.

```
VAPI webhook arrives
        ↓
Verify signature → Redis dedup (call_id)
        ↓
Embed summary → cosine similarity check against existing cluster centroids
        ↓
LLM receives: [conversation summary] + [current cluster list with descriptions]
        ↓
LLM decides:
  → fits cluster X: assign conversation, update centroid
  → no good match: call create_cluster tool → new cluster born immediately
        ↓
Dashboard updates in real-time
```

### LLM Tool Definition
```typescript
tools: [
  {
    name: "assign_to_cluster",
    description: "Assign conversation to an existing cluster",
    parameters: { cluster_id: string, confidence: number }
  },
  {
    name: "create_new_cluster", 
    description: "Create a new cluster for an emerging topic",
    parameters: { label: string, description: string }
  }
]
```

### Guardrail Against Fragmentation
Before LLM can call `create_new_cluster`, a hard cosine similarity check runs:
```python
# If any existing cluster centroid is within 0.15 cosine distance → force assignment
# Only allow new cluster creation if genuinely novel in embedding space
if min_distance < SIMILARITY_THRESHOLD:
    force_assign_to_nearest_cluster()
else:
    allow_llm_to_create_cluster()
```
This prevents "refund delay", "late refund", "refund taking too long" becoming 3 clusters instead of 1.

### Pros
- Emerging topics surface within minutes of first occurrence
- LLM understands semantic meaning — better judgment on edge cases
- No nightly job dependency
- Clusters have human-readable descriptions from day one (LLM writes them)

### Cons
- LLM sees one conversation at a time — never has global view
- Risk of cluster fragmentation without the cosine guardrail
- Requires LLM API (cost per conversation)
- Non-deterministic — same conversation might be classified differently on different runs
- Without global view, may miss that two clusters should be merged

---

## Approach 3: Hybrid (Recommended)

Combine both approaches — use each for what it does best.

```
Dynamic LLM clustering (real-time, per conversation)
    → immediate insight, emerging topics surface fast

        +

Weekly HDBSCAN merge job (global coherence pass)
    → finds clusters that should be merged
    → rebuilds centroids from ground truth embeddings
    → fixes any fragmentation from LLM drift
```

### How the Merge Job Works
1. Pull all embeddings + current cluster assignments
2. Run HDBSCAN on raw embeddings (ignore current LLM clusters)
3. Compare HDBSCAN clusters vs LLM clusters
4. Where HDBSCAN merges what LLM kept separate → flag for review or auto-merge
5. Update cluster centroids from ground truth

### Data Flow
```
Real-time path:  webhook → embed → LLM classify → immediate dashboard update
Batch path:      weekly HDBSCAN → merge overlapping clusters → rebalance
```

---

## Database Schema

```sql
CREATE TABLE conversations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vapi_call_id VARCHAR(255) UNIQUE NOT NULL,
  summary      TEXT NOT NULL,
  transcript   TEXT,
  duration_s   INTEGER,
  ended_reason VARCHAR(100),
  ingested_at  TIMESTAMPTZ DEFAULT now(),
  org_id       UUID NOT NULL
);

CREATE TABLE embeddings (
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  model_version   VARCHAR(50),
  vector          vector(384),
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON embeddings USING hnsw (vector vector_cosine_ops);

CREATE TABLE clusters (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      UUID NOT NULL,
  label       VARCHAR(500),
  description TEXT,
  centroid    vector(384),
  source      VARCHAR(20),  -- 'llm' | 'hdbscan' | 'merged'
  run_id      UUID,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE cluster_members (
  conversation_id UUID REFERENCES conversations(id),
  cluster_id      UUID REFERENCES clusters(id),
  distance        FLOAT,
  assigned_by     VARCHAR(20),  -- 'llm' | 'hdbscan'
  run_id          UUID,
  PRIMARY KEY (conversation_id, run_id)
);

CREATE TABLE insights (
  cluster_id    UUID REFERENCES clusters(id),
  sentiment     VARCHAR(20),
  volume        INTEGER,
  volume_delta  FLOAT,
  urgency_score FLOAT,
  computed_at   TIMESTAMPTZ DEFAULT now()
);
```

---

## Scalability Path

| Stage | Conversations | Architecture |
|---|---|---|
| MVP | 0–10k | Single Vercel function, Neon free tier, no queue |
| Growth | 10k–1M | Vercel Queues, HNSW index, Redis caching, nightly cron |
| Scale | 1M+ | Dedicated embedding service, batched GPU inference, Kafka |

---

## Decision Summary

| Decision | Choice | Reason |
|---|---|---|
| Input | VAPI summary (not full transcript) | Cleaner embeddings, no boilerplate noise, fast enough for inline processing |
| Embeddings | `all-MiniLM-L6-v2` | Free, local, 384-dim |
| Clustering (batch) | UMAP + HDBSCAN | Discovers unknown topics, no K needed |
| Clustering (real-time) | LLM + cosine guardrail | Semantic judgment + fragmentation prevention |
| Sentiment | `cardiffnlp/twitter-roberta-base-sentiment-latest` | Contextual, already loading transformers |
| Labeling | KeyBERT (batch) / LLM-generated (dynamic) | Best tool per approach |
| Primary DB | Neon Postgres + pgvector | One DB for vectors + relational data |
| Cache / Dedup | Redis (Upstash) | O(1) dedup, dashboard caching |
| Multi-tenancy | `org_id` on every table + RLS | Cannot retrofit later |
