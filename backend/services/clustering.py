import os
import json
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def assign_or_create_cluster(summary: str, existing_clusters: list[dict]) -> dict:
    cluster_context = "\n".join([
        f"- ID: {c['id']} | Label: {c['label']} | Description: {c['description']}"
        for c in existing_clusters
    ]) or "No clusters exist yet."

    tools = [
        {
            "type": "function",
            "function": {
                "name": "assign_to_cluster",
                "description": "Assign this conversation to an existing cluster",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "string"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["cluster_id", "reasoning"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_new_cluster",
                "description": "Create a new cluster for an intent not covered by existing clusters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Short label, max 6 words"},
                        "description": {"type": "string", "description": "One sentence describing the user intent"}
                    },
                    "required": ["label", "description"]
                }
            }
        }
    ]

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an intent classification engine for an AI agent analytics platform. "
                    "Cluster user conversations by their underlying intent. "
                    "Only create a new cluster if the intent is genuinely different from all existing ones. "
                    "Prefer assigning to an existing cluster when in doubt."
                )
            },
            {
                "role": "user",
                "content": (
                    f"New conversation summary:\n\"{summary}\"\n\n"
                    f"Existing clusters:\n{cluster_context}\n\n"
                    "Does this conversation fit an existing cluster, or is it a new topic?"
                )
            }
        ],
        tools=tools,
        tool_choice="required",
    )

    tool_call = response.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)

    if tool_call.function.name == "assign_to_cluster":
        matched = next((c for c in existing_clusters if c["id"] == args["cluster_id"]), None)
        return {
            "action": "assign",
            "cluster_id": args["cluster_id"],
            "label": matched["label"] if matched else "",
            "description": matched["description"] if matched else "",
        }
    else:
        return {
            "action": "create",
            "cluster_id": None,
            "label": args["label"],
            "description": args["description"],
        }
