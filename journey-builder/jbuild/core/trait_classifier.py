"""Trait Classifier orchestration for jbuild."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from .traits import TraitService, normalize_allowed_values, utc_now_iso


@dataclass
class TraitClassificationResult:
    tenant_id: int
    contact_id: str
    trait_id: str
    trait_key: str
    resolved_value: str
    confidence: float
    classifier_version: str
    reasoning: str | None
    raw_response: dict[str, Any] | None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)

    def to_trait_value_row(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "trait_id": self.trait_id,
            "resolved_value": self.resolved_value,
            "resolution_source": "classifier",
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "classifier_version": self.classifier_version,
            "source_metadata": {"raw_response": self.raw_response or {}},
            "resolved_at": utc_now_iso(),
        }


def format_conversation(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.get("direction") == "system":
            continue
        speaker = "Customer" if message.get("direction") == "inbound" else "Business"
        text = message.get("text") or "[non-text message]"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def compose_trait_prompt(master_prompt: str, trait_key: str, labels: list[str]) -> str:
    label_list = ", ".join(labels)
    return (
        f"{master_prompt.strip()}\n\n"
        f"Classify only the `{trait_key}` trait for this conversation.\n"
        f"Valid labels: {label_list}\n"
        "Return the single best trait value and confidence."
    )


class TraitClassifierRunner:
    """Runs one Trait Classifier config against one contact."""

    def __init__(
        self,
        service: TraitService,
        provider_factory: Callable[..., Any] | None = None,
    ):
        self.service = service
        self.provider_factory = provider_factory or self._default_provider_factory

    @staticmethod
    def _default_provider_factory(**kwargs):
        from scripts.classifiers.factory import get_classifier

        return get_classifier(**kwargs)

    def classify_contact(
        self,
        tenant_id: int,
        contact_id: str,
        *,
        trait_id: str | None = None,
        trait_key: str | None = None,
        config_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        classifier: Any | None = None,
    ) -> TraitClassificationResult:
        trait = self.service.get_trait_definition(
            tenant_id,
            trait_id=trait_id,
            trait_key=trait_key,
        )
        if trait is None:
            raise ValueError("Trait not found")

        resolved_trait_id = str(trait["trait_id"])
        if config_id:
            config = self.service.get_trait_classifier_config(tenant_id, resolved_trait_id, config_id)
        else:
            config = self.service.get_active_trait_classifier_config(tenant_id, resolved_trait_id)
        if config is None:
            raise ValueError(f"No Trait Classifier config for trait {resolved_trait_id}")

        labels = normalize_allowed_values(config.get("allowed_values_snapshot")) or normalize_allowed_values(
            trait.get("allowed_values")
        )
        if not labels:
            raise ValueError("Trait Classifier config has no allowed values")

        messages = self.service.get_contact_messages(tenant_id, contact_id)
        conversation = format_conversation(messages)
        if not conversation:
            fallback = "unknown" if "unknown" in labels else labels[0]
            return TraitClassificationResult(
                tenant_id=tenant_id,
                contact_id=contact_id,
                trait_id=resolved_trait_id,
                trait_key=str(trait["trait_key"]),
                resolved_value=fallback,
                confidence=0.0,
                classifier_version=self._classifier_version(classifier, config, provider, model),
                reasoning="no_messages",
                raw_response={"reasoning": "no_messages"},
            )

        active_classifier = classifier or self.provider_factory(
            provider=provider or config.get("provider"),
            model=model or config.get("model"),
        )
        prompt = compose_trait_prompt(str(config["master_prompt"]), str(trait["trait_key"]), labels)
        provider_result = active_classifier.classify(
            text=conversation,
            prompt=prompt,
            labels=labels,
        )

        raw_response = getattr(provider_result, "raw_response", None) or {}
        resolved_value = getattr(provider_result, "journey_stage", None) or raw_response.get("resolved_value")
        confidence = float(getattr(provider_result, "confidence", 0.0) or 0.0)
        if resolved_value not in labels:
            resolved_value = labels[0]
            confidence = 0.0

        return TraitClassificationResult(
            tenant_id=tenant_id,
            contact_id=contact_id,
            trait_id=resolved_trait_id,
            trait_key=str(trait["trait_key"]),
            resolved_value=str(resolved_value),
            confidence=confidence,
            classifier_version=self._classifier_version(active_classifier, config, provider, model),
            reasoning=raw_response.get("reasoning"),
            raw_response=raw_response,
        )

    def classify_and_write(self, *args, **kwargs) -> TraitClassificationResult:
        result = self.classify_contact(*args, **kwargs)
        self.service.upsert_contact_trait_values(result.tenant_id, [result.to_trait_value_row()])
        return result

    @staticmethod
    def _classifier_version(classifier: Any, config: dict[str, Any], provider: str | None, model: str | None) -> str:
        version = int(config.get("version") or 1)
        if classifier is not None and hasattr(classifier, "build_classifier_version"):
            return classifier.build_classifier_version(version)
        provider_name = provider or config.get("provider") or "unknown"
        model_name = model or config.get("model") or "unknown"
        return f"{provider_name}/{model_name}/v{version}"
