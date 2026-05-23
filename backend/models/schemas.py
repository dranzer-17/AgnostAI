from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VAPIMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None  # VAPI uses 'message' not 'content'
    time: Optional[float] = None

    model_config = {"extra": "allow"}

    def get_text(self) -> str:
        return self.content or self.message or ""


class VAPICall(BaseModel):
    id: str
    orgId: Optional[str] = None
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None
    endedReason: Optional[str] = None
    cost: Optional[float] = None


class VAPIAnalysis(BaseModel):
    sentiment: Optional[str] = None
    successEvaluation: Optional[str] = None


class VAPIWebhookMessage(BaseModel):
    type: Optional[str] = None
    call: Optional[VAPICall] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    messages: Optional[list[VAPIMessage]] = None
    analysis: Optional[VAPIAnalysis] = None

    model_config = {"extra": "allow"}


class VAPIWebhookPayload(BaseModel):
    message: Optional[VAPIWebhookMessage] = None

    # Also support flat structure (some VAPI events are not wrapped)
    type: Optional[str] = None
    call: Optional[VAPICall] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    messages: Optional[list[VAPIMessage]] = None
    analysis: Optional[VAPIAnalysis] = None

    model_config = {"extra": "allow"}

    def get_message(self) -> "VAPIWebhookMessage":
        """Returns the inner message regardless of whether payload is wrapped or flat."""
        if self.message:
            return self.message
        return VAPIWebhookMessage(
            type=self.type,
            call=self.call,
            transcript=self.transcript,
            summary=self.summary,
            messages=self.messages,
            analysis=self.analysis,
        )


class ClusterResponse(BaseModel):
    id: str
    label: str
    description: str
    volume: int
    sentiment: str
    frustration_index: float
    intent_resolution_rate: float
    volume_delta: float
    urgency_score: float
    created_at: datetime


class InsightResponse(BaseModel):
    clusters: list[ClusterResponse]
    total_conversations: int
    avg_frustration: float
    avg_resolution_rate: float
