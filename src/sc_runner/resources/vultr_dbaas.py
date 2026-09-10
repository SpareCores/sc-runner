"""Vultr Managed Database (Postgres) + companion benchmark VM in one Pulumi stack."""

from __future__ import annotations

import copy
import re
import secrets
import string

import ediri_vultr as vultr
import pulumi

from .azure_dbaas import export_dbaas_stack
from .managed_db import DbaasStackSpec
from .multi_vm import VmSpec, build_user_data_b64
from .vultr import resolve_plan

NETWORK_MODE = "private_vpc"


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _slug_label(slug: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9-]", "-", slug).strip("-")
    return (raw or "sc-dbaas")[:255]


def resources_vultr_dbaas(
    *,
    region: str,
    public_key: str,
    tags: list[str],
    instance_opts: dict,
    provider_opts: dict,
    os_name: str,
    disk_size: int,
    dbaas: DbaasStackSpec,
) -> None:
    """Provision VPC-attached Vultr managed Postgres + public client instance."""
    md = dbaas.managed_db
    slug = _slug_label(dbaas.instance_key_slug or "dbaas")
    instance_opts = copy.deepcopy(instance_opts)
    provider_opts = copy.deepcopy(provider_opts)
    tags = copy.deepcopy(tags)
    if not isinstance(tags, list):
        raise ValueError("tags must be a list of strings for Vultr (e.g. ['created-by:sc-runner'])")

    provider = vultr.Provider(
        resource_name=region,
        opts=pulumi.ResourceOptions(),
        **provider_opts,
    )
    opts = pulumi.ResourceOptions(provider=provider)
    vultr.get_region(
        filters=[vultr.GetRegionFilterArgs(name="id", values=[region])],
        opts=pulumi.InvokeOptions(provider=provider),
    )
    os_info = vultr.get_os(
        filters=[vultr.GetOsFilterArgs(name="name", values=[os_name])],
        opts=pulumi.InvokeOptions(provider=provider),
    )

    vpc = vultr.Vpc(
        slug,
        region=region,
        description=f"sc-runner-{slug}",
        opts=opts,
    )

    admin_password = md.admin_password or _random_password()
    plan = md.sku_name or md.native_id
    pg = vultr.Database(
        slug,
        database_engine="pg",
        database_engine_version=str(md.engine_version),
        label=slug,
        plan=plan,
        region=region,
        password=admin_password,
        vpc_id=vpc.id,
        tag="created-by:sc-runner",
        opts=opts,
    )

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
    # VPC-attached DBs expose the private hostname on ``host``.
    db_sources = {
        ("db", "fqdn"): pg.host,
        ("db", "port"): pg.port.apply(lambda p: str(p) if p else "5432"),
        ("db", "password"): pg.password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    if public_key:
        ssh_key = vultr.SSHKey(
            f"{slug}-client",
            name=f"{slug}-client",
            ssh_key=public_key,
            opts=opts,
        )
        ssh_key_ids = [ssh_key.id]
    else:
        ssh_key_ids = instance_opts.get("ssh_key_ids", [])

    client_plan = resolve_plan(
        dbaas.client_instance, dbaas.client_disk_gib or disk_size
    )
    client_opts = copy.deepcopy(instance_opts)
    client_opts["os_id"] = int(os_info.id)
    client_opts["user_data"] = client_user_data
    client_opts["ssh_key_ids"] = ssh_key_ids
    client_opts["tags"] = [*tags, f"name:{dbaas.client_instance}-client"]
    client_opts["vpc_ids"] = [vpc.id]

    client = vultr.Instance(
        f"{dbaas.client_instance}-client",
        region=region,
        plan=client_plan,
        label=f"{dbaas.client_instance}-client",
        hostname=f"{dbaas.client_instance}-client",
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[pg]),
        **client_opts,
    )

    db_port = pg.port.apply(lambda p: int(p) if p else 5432)
    admin_login = md.admin_login or "vultradmin"
    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=[region],
        db_fqdn=pg.host,
        db_port=db_port,
        db_bootstrap_login=admin_login,
        db_bootstrap_database=pg.dbname,
        db_admin_login=pg.user.apply(lambda u: u or admin_login),
        db_admin_password=pulumi.Output.secret(pg.password),
        client_private_ip=client.internal_ip,
        client_public_ip=client.main_ip,
        storage_gib=md.storage_gib,
        network_mode=NETWORK_MODE,
    )
