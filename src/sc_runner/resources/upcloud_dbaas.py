"""UpCloud Managed Database (Postgres) + companion benchmark VM in one Pulumi stack."""

from __future__ import annotations

import copy
import re
import secrets
import string

import pulumi
import pulumi_upcloud as upcloud

from .. import data as sc_data_helpers
from .azure_dbaas import export_dbaas_stack
from .managed_db import DbaasStackSpec, ManagedDbSpec
from .multi_vm import VmSpec, build_user_data_b64, user_data_plaintext
from .upcloud import private_cidr_for_slug

NETWORK_MODE = "private_vpc"
# Flexible (rdb.*) plans bill compute/storage/nodes separately; legacy bundled
# plans still use the single `plan` field.
# https://developers.upcloud.com/1.3/16-managed-database/
# https://upcloud.com/docs/products/managed-postgresql/configurations/
#
# Per-plan storage bands and backup tiers come from sc-data
# ``database.api_reference_object`` (crawler GET /1.3/database/plans).


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _service_name(slug: str) -> str:
    """UpCloud service name: unique hostname prefix, lowercase alphanumeric."""
    raw = re.sub(r"[^a-z0-9]", "", slug.lower())
    name = f"sc{raw}" if raw else "scdbaas"
    return name[:63]


def _is_flexible_plan(plan: str) -> bool:
    return plan.startswith("rdb.")


def _plan_node_count(ha_mode: str | None) -> int:
    """Map inspector ha_mode to UpCloud plan_node_count."""
    mode = (ha_mode or "standalone").strip().lower()
    if mode in ("standalone", "none", "single_zone", "single"):
        return 1
    if mode in ("2", "ha2"):
        return 2
    if mode in ("3", "ha3"):
        return 3
    # Readable / HA cluster paths default to 2 nodes.
    return 2


def _plan_backups(md: ManagedDbSpec, plan: str) -> str:
    """Backup tier allowed for the compute shape.

    Prefer ``ManagedDbSpec.plan_backups`` (from inspector), else
    ``api_reference_object.plan_backups`` in sc-data.
    """
    if md.plan_backups:
        return md.plan_backups
    meta = sc_data_helpers.upcloud_flexible_plan_meta(plan)
    allowed = meta.get("plan_backups") or []
    for pref in ("mini", "regular", "extended"):
        if pref in allowed:
            return pref
    raise ValueError(
        f"UpCloud flexible plan {plan!r} missing plan_backups in sc-data "
        "api_reference_object (and ManagedDbSpec.plan_backups unset)"
    )


def _storage_bands_for_plan(plan: str) -> tuple[int, tuple[tuple[int, int], ...]]:
    """Return (step_gib, bands) from sc-data api_reference_object.plan_storage."""
    meta = sc_data_helpers.upcloud_flexible_plan_meta(plan)
    ps = meta.get("plan_storage") or {}
    step = int(ps.get("step_gib") or 10)
    options = ps.get("options") or []
    bands = tuple(
        (int(option["base_gib"]), int(option["max_gib"]))
        for option in options
        if isinstance(option, dict) and "base_gib" in option and "max_gib" in option
    )
    if not bands:
        raise ValueError(
            f"UpCloud flexible plan {plan!r} missing "
            "api_reference_object.plan_storage bands in sc-data"
        )
    return step, bands


def _snap_storage_gib(storage_gib: int, plan: str) -> int:
    """Round to step and snap into a valid UpCloud storage band."""
    step, bands = _storage_bands_for_plan(plan)
    gib = max(step, int(storage_gib))
    gib = -(-gib // step) * step  # ceil to step
    for lo, hi in bands:
        if lo <= gib <= hi:
            return gib
    for lo, _hi in bands:
        if gib < lo:
            return lo
    return bands[-1][1]


def _postgres_plan_kwargs(md: ManagedDbSpec, plan: str) -> dict:
    """Build ManagedDatabasePostgresql plan args for flexible or legacy plans."""
    if not _is_flexible_plan(plan):
        return {"plan": plan}
    storage_gib = int(md.storage_gib or 0)
    if storage_gib <= 0:
        raise ValueError(
            f"UpCloud flexible plan {plan!r} requires storage_gib > 0 "
            "(plan_storage_gib)"
        )
    return {
        "plan_compute": plan,
        "plan_node_count": _plan_node_count(md.ha_mode),
        "plan_storage_gib": _snap_storage_gib(storage_gib, plan),
        "plan_backups": _plan_backups(md, plan),
    }


def resources_upcloud_dbaas(
    *,
    region: str,
    public_key: str,
    instance_opts: dict,
    dbaas: DbaasStackSpec,
) -> None:
    """Provision private-network UpCloud managed Postgres + public client server."""
    md = dbaas.managed_db
    slug = dbaas.instance_key_slug or "dbaas"
    service = _service_name(slug)
    instance_opts = copy.deepcopy(instance_opts)
    private_cidr, gateway = private_cidr_for_slug(slug)

    router = upcloud.Router(slug, name=f"{service}-router")
    network = upcloud.Network(
        slug,
        name=f"{service}-private",
        zone=region,
        router=router.id,
        ip_network=dict(
            address=private_cidr,
            dhcp=True,
            dhcp_default_route=False,
            family="IPv4",
            gateway=gateway,
        ),
    )

    admin_login = md.admin_login or "scadmin"
    admin_password = md.admin_password or _random_password()
    plan = md.sku_name or md.native_id

    props_kwargs: dict = {
        "version": str(md.engine_version),
        "admin_username": admin_login,
        "admin_password": admin_password,
        "public_access": False,
        "ip_filters": [private_cidr],
        "automatic_utility_network_ip_filter": True,
    }
    pg_kwargs: dict = dict(
        title=service,
        zone=region,
        name=service,
        termination_protection=False,
        networks=[
            {
                "family": "IPv4",
                "name": "pg",
                "type": "private",
                "uuid": network.id,
            }
        ],
        properties=upcloud.ManagedDatabasePostgresqlPropertiesArgs(**props_kwargs),
        **_postgres_plan_kwargs(md, plan),
    )
    pg = upcloud.ManagedDatabasePostgresql(slug, **pg_kwargs)

    default_bindings = {
        "SC_DB_HOST": ("db", "fqdn"),
        "SC_DB_PORT": ("db", "port"),
        "SC_DB_PASSWORD": ("db", "password"),
    }
    if dbaas.client_user_data_b64 and not (
        dbaas.client_user_data_bindings or dbaas.client_user_data_template
    ):
        client_bindings: dict[str, tuple[str, str]] = {}
    else:
        client_bindings = dbaas.client_user_data_bindings or default_bindings

    client_vm_spec = VmSpec(
        role="client",
        instance=dbaas.client_instance,
        disk_gib=dbaas.client_disk_gib,
        disk_type=dbaas.client_disk_type,
        user_data_b64=dbaas.client_user_data_b64,
        user_data_template=dbaas.client_user_data_template,
        user_data_static=dbaas.client_user_data_static,
        user_data_bindings=client_bindings,
    )
    db_sources = {
        ("db", "fqdn"): pg.service_host,
        ("db", "port"): pg.service_port.apply(lambda p: str(p) if p else "5432"),
        ("db", "password"): pg.service_password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    client_opts = copy.deepcopy(instance_opts)
    client_opts.update(
        dict(
            hostname=f"{dbaas.client_instance}-client".lower()[:64],
            plan=dbaas.client_instance,
            zone=region,
            login={"user": "root", "keys": [public_key], "create_password": False},
            template={
                "size": dbaas.client_disk_gib,
                "storage": "Ubuntu Server 24.04 LTS (Noble Numbat)",
            },
            network_interfaces=[
                {"type": "public"},
                {"type": "private", "network": network.id},
            ],
            metadata=True,
            user_data=user_data_plaintext(client_user_data),
        )
    )
    client = upcloud.Server(
        f"{dbaas.client_instance}-client",
        opts=pulumi.ResourceOptions(depends_on=[pg]),
        **client_opts,
    )

    def _iface_ip(ifaces, iface_type: str) -> str:
        return next((i.ip_address for i in ifaces if i.type == iface_type), "")

    client_public_ip = client.network_interfaces.apply(
        lambda ifaces: _iface_ip(ifaces, "public")
    )
    client_private_ip = client.network_interfaces.apply(
        lambda ifaces: _iface_ip(ifaces, "private")
    )
    db_port = pg.service_port.apply(lambda p: int(p) if p else 5432)

    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=[region],
        db_fqdn=pg.service_host,
        db_port=db_port,
        db_bootstrap_login=pg.service_username.apply(lambda u: u or admin_login),
        db_bootstrap_database=pg.primary_database,
        db_admin_login=pg.service_username.apply(lambda u: u or admin_login),
        db_admin_password=pulumi.Output.secret(pg.service_password),
        client_private_ip=client_private_ip,
        client_public_ip=client_public_ip,
        storage_gib=md.storage_gib,
        network_mode=NETWORK_MODE,
    )
