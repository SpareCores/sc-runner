"""Vendor-neutral managed database specification for DBaaS Pulumi stacks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ManagedDbSpec:
    """Managed Postgres (or other engine) provision parameters."""

    engine: str = "postgres"
    engine_version: str = "18"
    native_id: str = ""
    sku_name: str = ""
    sku_tier: str = ""
    ha_mode: str = "standalone"
    storage_gib: int = 128
    storage_type: str = "ManagedDiskV2"
    storage_iops_tier: str = "P30"
    admin_login: str = "scadmin"
    admin_password: str = ""
    database_name: str = "bench"


@dataclass
class DbaasStackSpec:
    """Single-stack spec: managed DB + companion benchmark VM."""

    managed_db: ManagedDbSpec
    client_instance: str
    client_disk_gib: int = 30
    client_disk_type: str | None = None
    client_user_data_b64: str | None = None
    client_user_data_template: str | None = None
    client_user_data_static: dict[str, str] = field(default_factory=dict)
    client_user_data_bindings: dict[str, tuple[str, str]] = field(default_factory=dict)
    topology: str = "dbaas"
    instance_key_slug: str = ""
    extra_exports: dict[str, Any] = field(default_factory=dict)
