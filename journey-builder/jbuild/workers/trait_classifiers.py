"""Batch helpers for Trait Classifier runs."""

from __future__ import annotations

from typing import Iterable

from jbuild.adapters.supabase import create_trait_service
from jbuild.core.trait_classifier import TraitClassifierRunner, TraitClassificationResult


def classify_contacts(
    tenant_id: int,
    contact_ids: Iterable[str],
    *,
    trait_id: str,
    config_id: str | None = None,
    write: bool = False,
    runner: TraitClassifierRunner | None = None,
) -> list[TraitClassificationResult]:
    active_runner = runner or TraitClassifierRunner(service=create_trait_service())
    results: list[TraitClassificationResult] = []
    for contact_id in contact_ids:
        if write:
            result = active_runner.classify_and_write(
                tenant_id,
                contact_id,
                trait_id=trait_id,
                config_id=config_id,
            )
        else:
            result = active_runner.classify_contact(
                tenant_id,
                contact_id,
                trait_id=trait_id,
                config_id=config_id,
            )
        results.append(result)
    return results
