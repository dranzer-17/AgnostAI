-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Raw conversations from VAPI
CREATE TABLE IF NOT EXISTS conversations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vapi_call_id        VARCHAR(255) UNIQUE NOT NULL,
    summary             TEXT NOT NULL,
    transcript          TEXT,
    duration_s          INTEGER,
    ended_reason        VARCHAR(100),
    vapi_sentiment      VARCHAR(20),
    success_evaluation  BOOLEAN,
    messages            JSONB,
    ingested_at         TIMESTAMPTZ DEFAULT now()
);

-- Embeddings (384-dim MiniLM vectors)
CREATE TABLE IF NOT EXISTS embeddings (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID REFERENCES conversations(id) ON DELETE CASCADE,
    model_version       VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
    vector              vector(384) NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS embeddings_hnsw_idx ON embeddings USING hnsw (vector vector_cosine_ops);

-- Clusters (dynamically created by LLM)
CREATE TABLE IF NOT EXISTS clusters (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    label               VARCHAR(500) NOT NULL,
    description         TEXT NOT NULL,
    centroid            vector(384),
    member_count        INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Conversation → cluster membership
CREATE TABLE IF NOT EXISTS cluster_members (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id     UUID REFERENCES conversations(id) ON DELETE CASCADE,
    cluster_id          UUID REFERENCES clusters(id) ON DELETE CASCADE,
    distance            FLOAT,
    assigned_at         TIMESTAMPTZ DEFAULT now(),
    UNIQUE(conversation_id)
);

-- Precomputed insights per cluster
CREATE TABLE IF NOT EXISTS insights (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cluster_id          UUID REFERENCES clusters(id) ON DELETE CASCADE UNIQUE,
    sentiment           VARCHAR(20),
    volume              INTEGER DEFAULT 0,
    volume_delta        FLOAT DEFAULT 0,
    frustration_index   FLOAT DEFAULT 0,
    intent_resolution_rate FLOAT DEFAULT 0,
    urgency_score       FLOAT DEFAULT 0,
    computed_at         TIMESTAMPTZ DEFAULT now()
);
