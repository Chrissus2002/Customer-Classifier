import os
from typing import Optional

from .base import BaseClassifier
from .llm_apis import OpenAICompatibleClassifier, AnthropicClassifier, GeminiClassifier


class MockClassifier(BaseClassifier):
    """Deterministic classifier for testing. No API calls."""

    provider_name = "mock"
    model_name = "mock-v1"

    def __init__(self, default_stage: str = "browsing", default_confidence: float = 0.95):
        self.default_stage = default_stage
        self.default_confidence = default_confidence

    def classify(self, text: str, prompt: str, labels: list[str]):
        from scripts.classifiers.models import ClassificationResult

        stage = self.default_stage if self.default_stage in labels else labels[0]
        return ClassificationResult(
            journey_stage=stage,
            confidence=self.default_confidence,
            classifier_version=self.build_classifier_version(),
            raw_response={"mock": True},
        )


def get_classifier(provider: Optional[str] = None, model: Optional[str] = None, **kwargs) -> BaseClassifier:
    """
    Factory that returns the right classifier based on provider name.

    Args:
        provider: Provider name (e.g., "deepseek", "openai", "mock").
                  Defaults to PRODUCTION_PROVIDER env var.
        model: Model name override.
        **kwargs: Passed to the classifier constructor (api_key, base_url).

    Returns:
        A BaseClassifier instance.
    """
    provider = provider or os.getenv("PRODUCTION_PROVIDER", "deepseek")

    if provider == "mock":
        return MockClassifier(**kwargs)

    if provider == "anthropic":
        return AnthropicClassifier(model=model, **kwargs)

    if provider == "gemini":
        return GeminiClassifier(model=model, **kwargs)

    return OpenAICompatibleClassifier(provider=provider, model=model, **kwargs)