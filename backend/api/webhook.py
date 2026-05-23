import os
import json
import hmac
import uuid
import logging
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import text
from db.database import AsyncSessionLocal
from models.schemas import VAPIWebhookPayload
from services.pipeline import run_pipeline
from services.frustration import compute_frustration_index
import redis.asyncio as aioredis

logger = logging.getLogger("agnost.webhook")

router = APIRouter()

VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
REDIS_URL = os.getenv("REDIS_URL", "")

_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is None and REDIS_URL:
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def verify_vapi_secret(secret: str) -> bool:
    if not VAPI_WEBHOOK_SECRET:
        return True
    return hmac.compare_digest(VAPI_WEBHOOK_SECRET, secret)


@router.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    body = await request.body()
    secret = request.headers.get("x-vapi-secret", "")

    if not verify_vapi_secret(secret):
        raise HTTPException(status_code=401, detail="Invalid secret")

    raw = json.loads(body)
    logger.info(f"[webhook] raw keys: {list(raw.keys())}")
    if "message" in raw:
        logger.info(f"[webhook] message type: {raw['message'].get('type')}")
    else:
        logger.info(f"[webhook] top-level type: {raw.get('type')}")

    payload = VAPIWebhookPayload(**raw)
    msg = payload.get_message()

    logger.info(f"[webhook] resolved type: {msg.type}, has_call: {msg.call is not None}, has_transcript: {bool(msg.transcript)}")

    if msg.type != "end-of-call-report" or not msg.call:
        return {"status": "ignored"}

    call_id = msg.call.id
    summary = msg.summary or msg.transcript

    if not summary:
        return {"status": "no_summary"}

    summary = summary[:1000]

    # Redis deduplication
    redis = get_redis()
    if redis:
        is_new = await redis.set(f"processed:{call_id}", 1, nx=True, ex=86400)
        if not is_new:
            return {"status": "duplicate"}

    # Messages + frustration
    messages = [{"role": m.role, "content": m.get_text(), "time": m.time} for m in (msg.messages or [])]
    success = None
    if msg.analysis and msg.analysis.successEvaluation:
        success = msg.analysis.successEvaluation.lower() == "true"
    frustration = compute_frustration_index(messages, msg.call.endedReason, success)

    # Duration
    duration = None
    if msg.call.startedAt and msg.call.endedAt:
        from datetime import datetime
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        try:
            start = datetime.strptime(msg.call.startedAt, fmt)
            end = datetime.strptime(msg.call.endedAt, fmt)
            duration = int((end - start).total_seconds())
        except Exception:
            pass

    async with AsyncSessionLocal() as db:
        # Load existing clusters
        result = await db.execute(text(
            "SELECT id, label, description FROM clusters ORDER BY created_at DESC"
        ))
        existing_clusters = [
            {"id": str(r["id"]), "label": r["label"], "description": r["description"]}
            for r in result.mappings().all()
        ]

        # ── Orchestrator: extract issue, then run sentiment + clustering in parallel ──
        sentiment, decision, clean_issue = await run_pipeline(summary, existing_clusters)
        logger.info(f"[pipeline] issue={clean_issue[:60]} | sentiment={sentiment['label']} | cluster={decision['action']}:{decision.get('label') or decision.get('cluster_id')}")

        # Store conversation (use clean_issue as summary so dashboard shows readable text)
        conv_id = str(uuid.uuid4())
        await db.execute(text("""
            INSERT INTO conversations
                (id, vapi_call_id, summary, transcript, duration_s, ended_reason,
                 vapi_sentiment, success_evaluation, messages)
            VALUES
                (:id, :call_id, :summary, :transcript, :duration_s, :ended_reason,
                 :vapi_sentiment, :success_eval, CAST(:messages AS jsonb))
        """), {
            "id": conv_id,
            "call_id": call_id,
            "summary": clean_issue,
            "transcript": msg.transcript,
            "duration_s": duration,
            "ended_reason": msg.call.endedReason,
            "vapi_sentiment": sentiment["label"],
            "success_eval": success,
            "messages": json.dumps(messages),
        })

        # Validate cluster_id is a real UUID — LLM sometimes hallucinates "NONE" or garbage
        valid_ids = {c["id"] for c in existing_clusters}
        if decision["action"] == "assign" and decision.get("cluster_id") not in valid_ids:
            decision["action"] = "create"
            decision["label"] = decision.get("label") or summary[:50]
            decision["description"] = decision.get("description") or summary[:120]

        if decision["action"] == "create":
            cluster_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO clusters (id, label, description, member_count)
                VALUES (:id, :label, :description, 1)
            """), {
                "id": cluster_id,
                "label": decision["label"],
                "description": decision["description"],
            })
        else:
            cluster_id = decision["cluster_id"]
            await db.execute(text("""
                UPDATE clusters SET member_count = member_count + 1, updated_at = now()
                WHERE id = :cluster_id
            """), {"cluster_id": cluster_id})

        # Assign conversation to cluster
        await db.execute(text("""
            INSERT INTO cluster_members (conversation_id, cluster_id)
            VALUES (:conv_id, :cluster_id)
            ON CONFLICT (conversation_id) DO UPDATE SET cluster_id = :cluster_id
        """), {"conv_id": conv_id, "cluster_id": cluster_id})

        # Upsert insight for this cluster
        await db.execute(text("""
            INSERT INTO insights (cluster_id, sentiment, volume, frustration_index,
                                  intent_resolution_rate, urgency_score)
            SELECT
                :cluster_id, :sentiment, COUNT(*),
                AVG(CASE WHEN c2.success_evaluation = true THEN 0.0 ELSE 1.0 END),
                SUM(CASE WHEN c2.success_evaluation = true THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0),
                COUNT(*) * (1 - SUM(CASE WHEN c2.success_evaluation = true THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0))
            FROM cluster_members cm
            JOIN conversations c2 ON c2.id = cm.conversation_id
            WHERE cm.cluster_id = :cluster_id
            ON CONFLICT (cluster_id) DO UPDATE
                SET sentiment = EXCLUDED.sentiment,
                    volume = EXCLUDED.volume,
                    frustration_index = EXCLUDED.frustration_index,
                    intent_resolution_rate = EXCLUDED.intent_resolution_rate,
                    urgency_score = EXCLUDED.urgency_score,
                    computed_at = now()
        """), {"cluster_id": cluster_id, "sentiment": sentiment["label"]})

        await db.commit()

    return {"status": "processed", "cluster_id": cluster_id, "action": decision["action"]}
