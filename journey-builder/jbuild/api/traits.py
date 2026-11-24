"""Trait routes for the jbuild API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from jbuild.adapters.supabase import create_trait_service
from jbuild.core.trait_classifier import TraitClassifierRunner
from jbuild.core.traits import TraitService


router = APIRouter(tags=["traits"])


def get_trait_service() -> TraitService:
    return create_trait_service()


class TraitDefinitionRequest(BaseModel):
    tenant_id: int
    trait_key: str
    value_type: str
    display_label: str | None = None
    description: str | None = None
    allowed_values: list[str] | None = None
    resolver_mode: str = "mixed"
    is_active: bool = True


class TraitValueRequest(BaseModel):
    tenant_id: int
    contact_id: str
    resolved_value: str
    resolution_source: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasoning: str | None = None
    classifier_version: str | None = None
    source_metadata: dict[str, Any] | None = None
    resolved_at: str | None = None


class TraitClassifierDraftRequest(BaseModel):
    tenant_id: int
    master_prompt: str
    provider: str | None = None
    model: str | None = None
    allowed_values_snapshot: list[str] | None = None
    notes: str | None = None


class TraitClassifierActivateRequest(BaseModel):
    tenant_id: int
    config_id: str


class TraitClassifierTestRequest(BaseModel):
    tenant_id: int
    contact_id: str
    config_id: str | None = None
    provider: str | None = None
    model: str | None = None


@router.get("/traits")
def list_traits(
    tenant_id: int,
    include_inactive: bool = False,
    service: TraitService = Depends(get_trait_service),
):
    return service.list_trait_definitions(tenant_id, include_inactive=include_inactive)


@router.post("/traits")
def create_trait(
    payload: TraitDefinitionRequest,
    service: TraitService = Depends(get_trait_service),
):
    try:
        return service.create_or_update_trait_definition(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/traits/{trait_id}/values")
def get_trait_values(
    trait_id: str,
    tenant_id: int,
    contact_id: str | None = None,
    service: TraitService = Depends(get_trait_service),
):
    contact_ids = [contact_id] if contact_id else None
    return service.get_contact_trait_values(tenant_id, contact_ids=contact_ids, trait_ids=[trait_id])


@router.post("/traits/{trait_id}/values")
def set_trait_value(
    trait_id: str,
    payload: TraitValueRequest,
    service: TraitService = Depends(get_trait_service),
):
    try:
        return service.set_contact_trait_value(
            payload.tenant_id,
            payload.contact_id,
            trait_id,
            payload.resolved_value,
            resolution_source=payload.resolution_source,
            confidence=payload.confidence,
            reasoning=payload.reasoning,
            classifier_version=payload.classifier_version,
            source_metadata=payload.source_metadata,
            resolved_at=payload.resolved_at,
        ).data
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/trait-classifiers/{trait_id}/drafts")
def save_trait_classifier_draft(
    trait_id: str,
    payload: TraitClassifierDraftRequest,
    service: TraitService = Depends(get_trait_service),
):
    try:
        return service.save_trait_classifier_draft(
            payload.tenant_id,
            trait_id,
            payload.master_prompt,
            provider=payload.provider,
            model=payload.model,
            allowed_values_snapshot=payload.allowed_values_snapshot,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trait-classifiers/{trait_id}/active")
def get_active_trait_classifier(
    trait_id: str,
    tenant_id: int,
    service: TraitService = Depends(get_trait_service),
):
    config = service.get_active_trait_classifier_config(tenant_id, trait_id)
    if config is None:
        raise HTTPException(status_code=404, detail="No active Trait Classifier config")
    return config


@router.post("/trait-classifiers/{trait_id}/activate")
def activate_trait_classifier(
    trait_id: str,
    payload: TraitClassifierActivateRequest,
    service: TraitService = Depends(get_trait_service),
):
    return service.activate_trait_classifier_config(payload.tenant_id, trait_id, payload.config_id).data


@router.post("/trait-classifiers/{trait_id}/tests")
def test_trait_classifier(
    trait_id: str,
    payload: TraitClassifierTestRequest,
    service: TraitService = Depends(get_trait_service),
):
    runner = TraitClassifierRunner(service=service)
    try:
        result = runner.classify_contact(
            payload.tenant_id,
            payload.contact_id,
            trait_id=trait_id,
            config_id=payload.config_id,
            provider=payload.provider,
            model=payload.model,
        )
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
