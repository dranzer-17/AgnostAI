from fastapi import APIRouter
from sqlalchemy import text
from db.database import AsyncSessionLocal

router = APIRouter()


@router.get("/insights")
async def get_insights():
    async with AsyncSessionLocal() as db:
        total = (await db.execute(text("SELECT COUNT(*) FROM conversations"))).scalar()

        rows = (await db.execute(text("""
            SELECT
                c.id, c.label, c.description, c.member_count,
                i.sentiment, i.volume, i.frustration_index,
                i.intent_resolution_rate, i.urgency_score,
                c.created_at
            FROM clusters c
            LEFT JOIN insights i ON i.cluster_id = c.id
            ORDER BY i.volume DESC NULLS LAST
        """))).mappings().all()

        clusters = []
        for r in rows:
            clusters.append({
                "id": str(r["id"]),
                "label": r["label"],
                "description": r["description"],
                "volume": r["volume"] or r["member_count"] or 0,
                "sentiment": r["sentiment"] or "NEUTRAL",
                "frustration_index": round(r["frustration_index"] or 0, 3),
                "intent_resolution_rate": round(r["intent_resolution_rate"] or 0, 3),
                "urgency_score": round(r["urgency_score"] or 0, 3),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        avg_frustration = sum(c["frustration_index"] for c in clusters) / len(clusters) if clusters else 0
        avg_resolution = sum(c["intent_resolution_rate"] for c in clusters) / len(clusters) if clusters else 0

        return {
            "clusters": clusters,
            "total_conversations": total,
            "avg_frustration": round(avg_frustration, 3),
            "avg_resolution_rate": round(avg_resolution, 3),
        }


@router.get("/insights/conversations")
async def get_conversations():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT c.id, c.vapi_call_id, c.summary, c.vapi_sentiment,
                   c.success_evaluation, c.duration_s, c.ended_reason, c.ingested_at,
                   cl.label as cluster_label
            FROM conversations c
            LEFT JOIN cluster_members cm ON cm.conversation_id = c.id
            LEFT JOIN clusters cl ON cl.id = cm.cluster_id
            ORDER BY c.ingested_at DESC
            LIMIT 50
        """))).mappings().all()

        return [
            {
                "id": str(r["id"]),
                "vapi_call_id": r["vapi_call_id"],
                "summary": r["summary"],
                "sentiment": r["vapi_sentiment"] or "NEUTRAL",
                "success": r["success_evaluation"],
                "duration_s": r["duration_s"],
                "ended_reason": r["ended_reason"],
                "ingested_at": r["ingested_at"].isoformat() if r["ingested_at"] else None,
                "cluster_label": r["cluster_label"] or "Unclustered",
            }
            for r in rows
        ]
