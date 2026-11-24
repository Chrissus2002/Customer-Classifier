"""Unit tests for the classifiers package."""

import os
import pytest
from unittest.mock import patch, MagicMock

from scripts.classifiers.models import ClassificationResult, ClassificationRequest
from scripts.classifiers.base import BaseClassifier
from scripts.classifiers.factory import MockClassifier, get_classifier


# ── Models ──────────────────────────────────────────────────────────

class TestClassificationResult:
    def test_create_result(self):
        result = ClassificationResult(
            journey_stage="browsing",
            confidence=0.85,
            classifier_version="mock/mock-v1/v1",
        )
        assert result.journey_stage == "browsing"
        assert result.confidence == 0.85
        assert result.raw_response is None

    def test_result_with_raw_response(self):
        result = ClassificationResult(
            journey_stage="purchase_intent",
            confidence=0.92,
            classifier_version="deepseek/deepseek-chat/v1",
            raw_response={"journey_stage": "purchase_intent", "confidence": 0.92},
        )
        assert result.raw_response["confidence"] == 0.92


class TestClassificationRequest:
    def test_create_request(self):
        req = ClassificationRequest(
            tenant_id=YOUR_TENANT_ID,
            contact_id="abc-123",
            messages=[{"text": "Hello", "direction": "inbound"}],
            stages=["browsing", "purchase_intent"],
        )
        assert req.tenant_id == YOUR_TENANT_ID
        assert len(req.messages) == 1
        assert req.prompt_template is None


# ── MockClassifier ──────────────────────────────────────────────────

class TestMockClassifier:
    def test_returns_deterministic_result(self):
        mock = MockClassifier(default_stage="browsing", default_confidence=0.95)
        result = mock.classify(
            text="Hello, I'm interested in your products",
            prompt="Classify this conversation",
            labels=["browsing", "purchase_intent", "order_support"],
        )
        assert result.journey_stage == "browsing"
        assert result.confidence == 0.95
        assert result.raw_response == {"mock": True}

    def test_falls_back_to_first_label_if_default_not_in_labels(self):
        mock = MockClassifier(default_stage="nonexistent")
        result = mock.classify(
            text="test",
            prompt="test",
            labels=["browsing", "purchase_intent"],
        )
        assert result.journey_stage == "browsing"

    def test_classifier_version_format(self):
        mock = MockClassifier()
        result = mock.classify(text="x", prompt="x", labels=["browsing"])
        assert result.classifier_version == "mock/mock-v1/v1"

    def test_custom_config_version(self):
        mock = MockClassifier()
        version = mock.build_classifier_version(config_version=3)
        assert version == "mock/mock-v1/v3"


# ── BaseClassifier ──────────────────────────────────────────────────

class TestBaseClassifier:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseClassifier()

    def test_subclass_must_implement_classify(self):
        class IncompleteClassifier(BaseClassifier):
            pass

        with pytest.raises(TypeError):
            IncompleteClassifier()


# ── Factory ─────────────────────────────────────────────────────────

class TestFactory:
    def test_get_mock_classifier(self):
        classifier = get_classifier(provider="mock")
        assert isinstance(classifier, MockClassifier)

    @patch.dict(os.environ, {"PRODUCTION_PROVIDER": "mock"})
    def test_defaults_to_env_provider(self):
        classifier = get_classifier()
        assert isinstance(classifier, MockClassifier)

    def test_deepseek_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="API key not found"):
                get_classifier(provider="deepseek")

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"})
    def test_deepseek_instantiates_with_key(self):
        from scripts.classifiers.llm_apis import OpenAICompatibleClassifier
        classifier = get_classifier(provider="deepseek")
        assert isinstance(classifier, OpenAICompatibleClassifier)
        assert classifier.provider_name == "deepseek"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_openai_provider(self):
        from scripts.classifiers.llm_apis import OpenAICompatibleClassifier
        classifier = get_classifier(provider="openai", model="gpt-4o-mini")
        assert isinstance(classifier, OpenAICompatibleClassifier)
        assert classifier.provider_name == "openai"
        assert classifier.model_name == "gpt-4o-mini"


# ── OpenAICompatibleClassifier ──────────────────────────────────────

class TestOpenAICompatibleClassifier:
    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"})
    def test_builds_classifier_version(self):
        from scripts.classifiers.llm_apis import OpenAICompatibleClassifier
        c = OpenAICompatibleClassifier(provider="deepseek", model="deepseek-chat")
        assert c.build_classifier_version(2) == "deepseek/deepseek-chat/v2"

    def test_custom_provider_requires_base_url(self):
        from scripts.classifiers.llm_apis import OpenAICompatibleClassifier
        with pytest.raises(ValueError, match="No known base URL"):
            OpenAICompatibleClassifier(
                provider="custom-local", api_key="test", model="test"
            )

    def test_custom_provider_with_base_url(self):
        from scripts.classifiers.llm_apis import OpenAICompatibleClassifier
        c = OpenAICompatibleClassifier(
            provider="ollama",
            model="llama3",
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        assert c.provider_name == "ollama"
        assert c.model_name == "llama3"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_gemini_provider(self):
        from scripts.classifiers.llm_apis import GeminiClassifier
        c = GeminiClassifier(model="gemini-pro")
        assert c.provider_name == "gemini"
        assert c.model_name == "gemini-pro"
