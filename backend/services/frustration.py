import re
from services.sentiment import analyze


CLARIFICATION_PHRASES = [
    "what do you mean", "i don't understand", "can you repeat",
    "what?", "sorry?", "huh?", "please explain", "i'm confused",
    "that doesn't make sense", "what are you saying"
]

ESCALATION_PHRASES = [
    "let me speak to", "transfer me", "i want a manager",
    "this is unacceptable", "this is ridiculous", "i'm done",
    "cancel my", "i'm leaving", "worst", "terrible service"
]


def compute_frustration_index(
    messages: list[dict],
    ended_reason: str | None,
    success_evaluation: bool | None,
) -> float:
    """
    Frustration Index: 0.0 (calm) to 1.0 (highly frustrated)

    Components:
      - Repeated questions: user asking same thing multiple times
      - Clarification requests: confusion signals
      - Escalation phrases: "I want a manager", "cancel my account"
      - Sentiment degradation: sentiment worsening turn-by-turn
      - Failed resolution: successEvaluation = false
      - Abrupt end: call ended by customer unexpectedly
    """
    if not messages:
        return 0.0

    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        return 0.0

    score = 0.0
    total_user_turns = len(user_messages)
    user_texts = [m.get("content", "").lower() for m in user_messages]

    # 1. Repeated questions (same user message appearing 2+ times)
    seen = {}
    for text in user_texts:
        key = text[:40]
        seen[key] = seen.get(key, 0) + 1
    repeated = sum(1 for count in seen.values() if count > 1)
    score += min(repeated / max(total_user_turns, 1), 0.25)  # max 0.25

    # 2. Clarification requests
    clarification_count = sum(
        1 for text in user_texts
        if any(phrase in text for phrase in CLARIFICATION_PHRASES)
    )
    score += min(clarification_count / max(total_user_turns, 1), 0.2)  # max 0.2

    # 3. Escalation phrases
    escalation_count = sum(
        1 for text in user_texts
        if any(phrase in text for phrase in ESCALATION_PHRASES)
    )
    score += min(escalation_count * 0.15, 0.3)  # max 0.3

    # 4. Sentiment degradation across turns
    if len(user_messages) >= 3:
        first_half = " ".join(user_texts[:len(user_texts)//2])
        second_half = " ".join(user_texts[len(user_texts)//2:])
        first_sentiment = analyze(first_half)
        second_sentiment = analyze(second_half)
        if first_sentiment["label"] != "NEGATIVE" and second_sentiment["label"] == "NEGATIVE":
            score += 0.15  # conversation got worse

    # 5. Failed resolution
    if success_evaluation is False:
        score += 0.1

    # 6. Customer ended call (not agent, not natural end)
    if ended_reason in ("customer-ended-call", "customer-did-not-answer"):
        score += 0.05

    return round(min(score, 1.0), 4)
