import json
import os
import re
from typing import Dict, Optional

# OpenAI is the baseline dep (used by DeepSeek and any OpenAI-compatible
# provider) so it's imported unconditionally.
from openai import OpenAI

# google.genai and anthropic are OPTIONAL deps — only needed if you
# instantiate the corresponding classifier. They're lazy-imported inside
# the class __init__ so users running DeepSeek/OpenAI/Mistral/Ollama
# don't need to install ~15 MB of unused SDKs.
#   - google-genai: required for GeminiClassifier
#   - anthropic:    required for AnthropicClassifier
# If you see ImportError when instantiating one of these, add the
# corresponding package to requirements.txt.

from .base import BaseClassifier
from .models import ClassificationResult

# Known providers and their base URLs
PROVIDER_URLS: Dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1/",
}

# Env var names for API keys per provider
PROVIDER_KEY_ENV = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": "OLLAMA_API_KEY"
}


class OpenAICompatibleClassifier(BaseClassifier):
    """
    Generic classifier for any LLM with an OpenAI-compatible API.

    Works out of the box with DeepSeek, OpenAI, Mistral, and any local
    model server (Ollama, vLLM, etc.) that exposes the same interface.

    Usage:
        # Known provider (auto-resolves base_url and api_key env var)
        classifier = OpenAICompatibleClassifier(provider="deepseek")

        # Custom / local provider
        classifier = OpenAICompatibleClassifier(
            provider="ollama",
            model="llama3",
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )
    """

    def __init__(self, provider: str = "deepseek", model: Optional[str] = None, 
                api_key: Optional[str] = None, base_url: Optional[str] = None):

        self.provider_name = provider

        # Resolve API key
        resolved_key = api_key or os.getenv(
            PROVIDER_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
        )
        if not resolved_key:
            env_var = PROVIDER_KEY_ENV.get(provider, f"{provider.upper()}_API_KEY")
            raise ValueError(
                f"API key not found for provider '{provider}'. "
                f"Set {env_var} in .env or pass api_key."
            )

        # Resolve base URL
        self.base_url = base_url or PROVIDER_URLS.get(provider)
        if not self.base_url:
            raise ValueError(
                f"No known base URL for provider '{provider}'. Pass base_url explicitly."
            )

        # Resolve model
        self.model_name = model or os.getenv("PRODUCTION_MODEL", "deepseek-chat")
        # Only create OpenAI client for non-Gemini providers
        self.client = OpenAI(api_key=resolved_key, base_url=self.base_url)
    
    def _strip_markdown_fences(self, text: str) -> str:
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        return stripped.strip()

    def classify(self,text: str,prompt: str,labels: list[str]) -> ClassificationResult:
        labels_str = ", ".join(labels)
        system_prompt = (
            f"{prompt}\n\n"
            f"Valid labels: {labels_str}\n\n"
            f"Respond with JSON in the following format:\n"
            f"Responde en este formato JSON:\n"
            f'{{\n'
            f'    "reasoning": "analysis of the clients journey stage",\n'
            f'    "journey_stage": "intent_key",\n'
            f'    "resumen_conversación": "summary of the journey stage (1-2 oraciones)",\n'
            f'    "confidence": 0.0-1.0\n'
            f'}}'
        )
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        if response == None or response.choices[0].message.content == None:
            raise ValueError("LLM returned null content")

        raw_content = self._strip_markdown_fences(response.choices[0].message.content)
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned malformed JSON: {e} | raw: {raw_content!r}")

        stage = parsed.get("journey_stage", labels[0])
        confidence = float(parsed.get("confidence", 0.0))

        # Validate stage is one of the allowed labels
        if stage not in labels:
            stage = labels[0]
            confidence = 0.0

        return ClassificationResult(
            journey_stage=stage,
            confidence=confidence,
            classifier_version=self.build_classifier_version(),
            raw_response=parsed,
        )



class GeminiClassifier(BaseClassifier):

    provider_name = "gemini"

    def __init__(self, model: Optional[str] = None):
        google_api_key = os.getenv("GEMINI_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")

        # Lazy import: google-genai is only needed if someone actually uses
        # the Gemini classifier. See the module-level comment for rationale.
        try:
            from google import genai
        except ImportError as e:
            raise ImportError(
                "GeminiClassifier requires 'google-genai'. "
                "Install it with: pip install google-genai"
            ) from e
        self._genai = genai

        self.model_name = model or "gemini-2.5-flash"
        self.client = genai.Client(api_key=google_api_key)

    def _strip_markdown_fences(self, text: str) -> str:
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        return stripped.strip()

    def classify(self, text: str, prompt: str, labels: list[str]) -> ClassificationResult:
        labels_str = ", ".join(labels)
        system_prompt = (
            f"{prompt}\n\n"
            f"Valid labels: {labels_str}\n\n"
            f"Respond with JSON only, no markdown fences: "
            f'{{"journey_stage": "<label>", "confidence": <0.0-1.0>}}'
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=text,
            config=self._genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
            ),
        )
        raw_content = response.text
        if raw_content is None:
            raise ValueError("LLM returned null content")

        cleaned = self._strip_markdown_fences(raw_content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned malformed JSON: {e} | raw: {cleaned!r}")

        stage = parsed.get("journey_stage", labels[0])
        confidence = float(parsed.get("confidence", 0.0))

        if stage not in labels:
            stage = labels[0]
            confidence = 0.0

        return ClassificationResult(
            journey_stage=stage,
            confidence=confidence,
            classifier_version=self.build_classifier_version(),
            raw_response=parsed,
        )


class AnthropicClassifier(BaseClassifier):
    """
    Classifier using Anthropic's Claude via the Messages API.

    Usage:
        classifier = AnthropicClassifier()  # uses ANTHROPIC_API_KEY env var
        classifier = AnthropicClassifier(api_key="sk-...", model="claude-sonnet-4-5-20250929")
    """

    provider_name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "API key not found for provider 'anthropic'. "
                "Set ANTHROPIC_API_KEY in .env or pass api_key."
            )

        # Lazy import: anthropic is only needed if someone actually uses
        # this classifier. See the module-level comment for rationale.
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ImportError(
                "AnthropicClassifier requires 'anthropic'. "
                "Install it with: pip install anthropic"
            ) from e

        self.model_name = model or "claude-sonnet-4-5-20250929"
        self.client = Anthropic(api_key=resolved_key)

    def _strip_markdown_fences(self, text: str) -> str:
        """Strip ```json ... ``` fences that Claude sometimes wraps around JSON."""
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        return stripped.strip()

    def classify(self, text: str, prompt: str, labels: list[str]) -> ClassificationResult:
        labels_str = ", ".join(labels)
        system_prompt = (
            f"{prompt}\n\n"
            f"Valid labels: {labels_str}\n\n"
            f"Respond with JSON only, no markdown fences: "
            f'{{"journey_stage": "<label>", "confidence": <0.0-1.0>}}'
        )

        response = self.client.messages.create(
            model=self.model_name,
            system=system_prompt,
            messages=[
                {"role": "user", "content": text},
            ],
            max_tokens=256,
            temperature=0.1,
        )

        if response == None or response.content[0] == None or response.content[0].text == None:
            raise ValueError("LLM returned null content")

        raw_content = response.content[0].text
        cleaned = self._strip_markdown_fences(raw_content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned malformed JSON: {e} | raw: {cleaned!r}")

        stage = parsed.get("journey_stage", labels[0])
        confidence = float(parsed.get("confidence", 0.0))

        if stage not in labels:
            stage = labels[0]
            confidence = 0.0

        return ClassificationResult(
            journey_stage=stage,
            confidence=confidence,
            classifier_version=self.build_classifier_version(),
            raw_response=parsed,
        )
