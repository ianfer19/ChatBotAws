"""Capa infrastructure del slice tenant_prompts. Adapters de persistencia."""

from slices.tenant_prompts.infrastructure.local_json import LocalJsonTenantRepository

__all__ = ["LocalJsonTenantRepository"]
