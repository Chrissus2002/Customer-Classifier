"""Command line interface for headless jbuild operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from jbuild.core.trait_classifier import TraitClassifierRunner
from jbuild.core.traits import TraitService, normalize_allowed_values
from jbuild.adapters.supabase import create_trait_service


def _echo_json(value: Any) -> None:
    data = getattr(value, "data", value)
    click.echo(json.dumps(data, indent=2, sort_keys=True, default=str))


def _service() -> TraitService:
    return create_trait_service()


@click.group()
def cli() -> None:
    """Headless jbuild CLI."""


@cli.group()
def traits() -> None:
    """Manage trait definitions and current trait values."""


@traits.command("list")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--include-inactive", is_flag=True, default=False)
def traits_list(tenant_id: int, include_inactive: bool) -> None:
    _echo_json(_service().list_trait_definitions(tenant_id, include_inactive=include_inactive))


@traits.command("create")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--key", "trait_key", required=True)
@click.option("--type", "value_type", required=True)
@click.option("--label", "display_label")
@click.option("--description")
@click.option("--values", "allowed_values")
@click.option("--resolver-mode", default="mixed", show_default=True)
def traits_create(
    tenant_id: int,
    trait_key: str,
    value_type: str,
    display_label: str | None,
    description: str | None,
    allowed_values: str | None,
    resolver_mode: str,
) -> None:
    try:
        _echo_json(
            _service().create_or_update_trait_definition(
                tenant_id,
                trait_key,
                value_type,
                display_label=display_label,
                description=description,
                allowed_values=normalize_allowed_values(allowed_values),
                resolver_mode=resolver_mode,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@traits.group("values")
def trait_values() -> None:
    """Read and write current trait values."""


@trait_values.command("set")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--contact", "contact_id", required=True)
@click.option("--trait", "trait_id_or_key", required=True)
@click.option("--value", "resolved_value", required=True)
@click.option("--source", "resolution_source", required=True)
@click.option("--confidence", type=float)
@click.option("--reasoning")
def trait_values_set(
    tenant_id: int,
    contact_id: str,
    trait_id_or_key: str,
    resolved_value: str,
    resolution_source: str,
    confidence: float | None,
    reasoning: str | None,
) -> None:
    try:
        _echo_json(
            _service().set_contact_trait_value(
                tenant_id,
                contact_id,
                trait_id_or_key,
                resolved_value,
                resolution_source=resolution_source,
                confidence=confidence,
                reasoning=reasoning,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@trait_values.command("get")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--contact", "contact_id", multiple=True)
@click.option("--trait", "trait_key", multiple=True)
def trait_values_get(tenant_id: int, contact_id: tuple[str, ...], trait_key: tuple[str, ...]) -> None:
    _echo_json(
        _service().get_contact_trait_values(
            tenant_id,
            contact_ids=list(contact_id) or None,
            trait_keys=list(trait_key) or None,
        )
    )


@cli.group("trait-classifiers")
def trait_classifiers() -> None:
    """Manage and run Trait Classifiers."""


@trait_classifiers.command("draft")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--trait", "trait_id_or_key", required=True)
@click.option("--prompt")
@click.option("--prompt-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--provider")
@click.option("--model")
@click.option("--values", "allowed_values")
@click.option("--notes")
def trait_classifier_draft(
    tenant_id: int,
    trait_id_or_key: str,
    prompt: str | None,
    prompt_file: Path | None,
    provider: str | None,
    model: str | None,
    allowed_values: str | None,
    notes: str | None,
) -> None:
    if prompt_file:
        prompt = prompt_file.read_text()
    if not prompt:
        raise click.ClickException("--prompt or --prompt-file is required")
    try:
        service = _service()
        trait_id = service.require_trait_id(tenant_id, trait_id_or_key)
        _echo_json(
            service.save_trait_classifier_draft(
                tenant_id,
                trait_id,
                prompt,
                provider=provider,
                model=model,
                allowed_values_snapshot=normalize_allowed_values(allowed_values),
                notes=notes,
            )
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@trait_classifiers.command("activate")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--trait", "trait_id_or_key", required=True)
@click.option("--config", "config_id", required=True)
def trait_classifier_activate(tenant_id: int, trait_id_or_key: str, config_id: str) -> None:
    try:
        service = _service()
        trait_id = service.require_trait_id(tenant_id, trait_id_or_key)
        _echo_json(service.activate_trait_classifier_config(tenant_id, trait_id, config_id))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@trait_classifiers.command("test")
@click.option("--tenant", "tenant_id", type=int, required=True)
@click.option("--contact", "contact_id", required=True)
@click.option("--trait", "trait_id_or_key", required=True)
@click.option("--config", "config_id")
@click.option("--provider")
@click.option("--model")
def trait_classifier_test(
    tenant_id: int,
    contact_id: str,
    trait_id_or_key: str,
    config_id: str | None,
    provider: str | None,
    model: str | None,
) -> None:
    try:
        service = _service()
        trait_id = service.require_trait_id(tenant_id, trait_id_or_key)
        result = TraitClassifierRunner(service=service).classify_contact(
            tenant_id,
            contact_id,
            trait_id=trait_id,
            config_id=config_id,
            provider=provider,
            model=model,
        )
        _echo_json(result.model_dump())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
