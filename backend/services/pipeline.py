"""
Multi-agent pipeline: orchestrator fans out to sentiment agent + clustering agent in parallel.
"""
import os
import json
import asyncio
from groq import Groq

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


# ── Summarization Agent ───────────────────────────────────────────────────────

def _extract_issue(transcript: str) -> str:
    """Extracts a clean 1-2 sentence description of the user's problem from the transcript."""
    response = get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract the user's core problem from this support call transcript. "
                    "Write 1-2 sentences. You MUST include ALL of:\n"
                    "1. The EXACT feature or tool name (e.g. 'email sending', 'login flow', 'billing page', 'onboarding wizard')\n"
                    "2. The EXACT error behavior or failure mode (e.g. 'throws address-not-found error', 'returns 500', 'spinner never stops')\n"
                    "3. The affected product area (e.g. 'email agent', 'CRM integration', 'payment module')\n"
                    "Do NOT be vague — 'something is not working' is unacceptable. "
                    "Do NOT include greetings, agent responses, or resolution steps. "
                    "Different features = different descriptions even if they sound related."
                ),
            },
            {"role": "user", "content": transcript[:2000]},
        ],
        max_tokens=100,
        temperature=0,
    )
    return response.choices[0].message.content.strip()


# ── Sentiment Agent ────────────────────────────────────────────────────────────

def _sentiment_agent(summary: str) -> dict:
    """Returns { label: POSITIVE | NEGATIVE | NEUTRAL }"""
    response = get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a sentiment analysis agent for a support platform. "
                    "Classify the customer's sentiment in this support conversation. "
                    "Reply with exactly one word: POSITIVE, NEGATIVE, or NEUTRAL."
                ),
            },
            {"role": "user", "content": summary[:1000]},
        ],
        max_tokens=5,
        temperature=0,
    )
    label = response.choices[0].message.content.strip().upper()
    if label not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
        label = "NEUTRAL"
    return {"label": label}


# ── Clustering Agent ───────────────────────────────────────────────────────────

def _clustering_agent(summary: str, existing_clusters: list[dict]) -> dict:
    """
    Uses two tools: assign_to_cluster or create_new_cluster.
    Only assigns if the intent is clearly the same — different topics always create a new cluster.
    """
    cluster_context = "\n".join([
        f"- ID: {c['id']} | Label: {c['label']} | Description: {c['description']}"
        for c in existing_clusters
    ]) or "No clusters exist yet."

    tools = [
        {
            "type": "function",
            "function": {
                "name": "assign_to_cluster",
                "description": "Assign to an existing cluster ONLY if the user's core problem is identical to an existing cluster's description.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["cluster_id", "reasoning"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_new_cluster",
                "description": "Create a new cluster when the user's problem is a distinct topic not already represented.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "2-4 word category title. Examples: 'Email Sending Error', 'Login Failure', 'Billing Issue', 'Client Onboarding Error'. NO full sentences."},
                        "description": {"type": "string", "description": "2-3 sentences describing what this cluster represents. Include: (1) which feature/agent is affected, (2) what the error behavior looks like, (3) what type of user problems belong here. Example: 'This cluster covers errors in the client onboarding agent where client data such as name, email, or company is missing or not passed correctly to the agent. Symptoms include the agent failing to greet the client by name or being unable to proceed due to missing context.'"},
                    },
                    "required": ["label", "description"],
                },
            },
        },
    ]

    response = get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an intent clustering agent for an AI agent analytics platform. "
                    "Your job: decide if a new conversation belongs to an existing cluster or needs a new one.\n\n"
                    "STRICT RULES:\n"
                    "- Only assign to an existing cluster if the user's EXACT feature AND EXACT error type both match.\n"
                    "- 'Email sending error' and 'onboarding error' are DIFFERENT clusters even if both involve agents.\n"
                    "- 'Login issue' and 'billing issue' are DIFFERENT clusters even if both are account-related.\n"
                    "- Different features = different clusters. Different error modes = different clusters.\n"
                    "- When in doubt, CREATE a new cluster. Precision always beats consolidation.\n"
                    "- When creating, the 'label' must be a SHORT 2-4 word category title like 'Email Sending Error' — never a full sentence."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"New conversation summary:\n\"{summary}\"\n\n"
                    f"Existing clusters:\n{cluster_context}\n\n"
                    "Is this the exact same problem as an existing cluster, or a new distinct issue?"
                ),
            },
        ],
        tools=tools,
        tool_choice="required",
    )

    tool_call = response.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)

    if tool_call.function.name == "assign_to_cluster":
        cluster_id = args.get("cluster_id", "")
        matched = next((c for c in existing_clusters if c["id"] == cluster_id), None)
        # If LLM hallucinated a fake/invalid cluster_id, treat as create
        if not matched:
            return {
                "action": "create",
                "cluster_id": None,
                "label": args.get("label", summary[:40]),
                "description": args.get("description", summary[:100]),
            }
        return {
            "action": "assign",
            "cluster_id": cluster_id,
            "label": matched["label"],
            "description": matched["description"],
        }
    else:
        return {
            "action": "create",
            "cluster_id": None,
            "label": args["label"],
            "description": args["description"],
        }


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def run_pipeline(raw_summary: str, existing_clusters: list[dict]) -> tuple[dict, dict, str]:
    """
    Step 1: Extract clean issue from transcript.
    Step 2: Run sentiment + clustering in parallel on the clean issue.
    Returns (sentiment_result, clustering_result, clean_issue).
    """
    # If it looks like a raw transcript, extract the core issue first
    if raw_summary.startswith("AI:") or raw_summary.startswith("User:"):
        clean_issue = await asyncio.to_thread(_extract_issue, raw_summary)
    else:
        clean_issue = raw_summary

    sentiment_result, clustering_result = await asyncio.gather(
        asyncio.to_thread(_sentiment_agent, clean_issue),
        asyncio.to_thread(_clustering_agent, clean_issue, existing_clusters),
    )
    return sentiment_result, clustering_result, clean_issue
