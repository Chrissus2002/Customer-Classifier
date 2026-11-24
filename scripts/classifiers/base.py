from abc import ABC, abstractmethod

from .models import ClassificationResult


class BaseClassifier(ABC):
    """Abstract base class for LLM classification providers."""

    provider_name: str = "base"
    model_name: str = "unknown"

    @abstractmethod
    def classify(self, text: str, prompt: str, labels: list[str]) -> ClassificationResult:
        """
        Classify text into one of the provided labels.

        Args:
            text: The conversation text to classify.
            prompt: System prompt / instructions for the LLM.
            labels: Valid label names (journey stages).

        Returns:
            ClassificationResult with stage, confidence, and version info.
        """
        pass

    def build_classifier_version(self, config_version: int = 1) -> str:
        """Build a classifier_version string for result tracking."""
        return f"{self.provider_name}/{self.model_name}/v{config_version}"
