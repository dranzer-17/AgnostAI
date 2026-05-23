import os
from groq import Groq

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def analyze(text: str) -> dict:
    """Returns { label: POSITIVE|NEGATIVE|NEUTRAL, score: 1.0 }"""
    response = get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Classify the sentiment of this support conversation as exactly one word: POSITIVE, NEGATIVE, or NEUTRAL. Reply with only that one word."},
            {"role": "user", "content": text[:1000]},
        ],
        max_tokens=5,
        temperature=0,
    )
    label = response.choices[0].message.content.strip().upper()
    if label not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
        label = "NEUTRAL"
    return {"label": label, "score": 1.0}
