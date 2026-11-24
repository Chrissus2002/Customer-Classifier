from pydantic import BaseModel
from typing import Optional


class ClassificationResult(BaseModel):
    """Result from an LLM classification call."""
    journey_stage: str
    confidence: float
    classifier_version: str  # e.g., "deepseek/deepseek-chat/v2"
    raw_response: Optional[dict] = None


class ClassificationRequest(BaseModel):
    """Input for classifying a contact's conversation."""
    tenant_id: int
    contact_id: str
    messages: list[dict]  # [{text, direction, timestamp}, ...]
    stages: list[str]  # e.g., ["browsing", "purchase_intent", ...]
    prompt_template: Optional[str] = None
