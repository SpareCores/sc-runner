"""GCP Cloud SQL for PostgreSQL + companion benchmark VM in one Pulumi stack."""

from __future__ import annotations

import base64
import copy
import re
import secrets
import string

import pulumi
import pulumi_gcp as gcp

from .azure_dbaas import export_dbaas_stack
from .managed_db import DbaasStackSpec
from .multi_vm import VmSpec, build_user_data_b64

NETWORK_MODE = "private_vpc"
CLIENT_SUBNET_CIDR = "10.0.1.0/24"
PSA_PREFIX_LENGTH = 16


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _sql_instance_name(slug: str) -> str:
    """Cloud SQL instance name: lowercase, starts with a letter, max 98 chars."""
    raw = re.sub(r"[^a-z0-9-]", "", slug.lower())
    name = f"sc-{raw}".strip("-")
    if not name[0].isalpha():
        name = f"sc{name}"
    return name[:98].rstrip("-")


def _postgres_version(engine_version: str) -> str:
    major = str(engine_version).split(".", 1)[0]
    return f"POSTGRES_{major}"


def _cloud_sql_tier(md) -> str:
    return md.sku_name or "db-perf-optimized-N-16"


def resources_gcp_dbaas(
    *,
    zone: str,
    public_key: str,
    instance_opts: dict,
    bootdisk_opts: dict,
    bootdisk_init_opts: dict,
    scheduling_opts: dict,
    dbaas: DbaasStackSpec,
) -> None:
    """Provision Cloud SQL (private IP) and a client VM in the same VPC."""
    md = dbaas.managed_db
    slug = dbaas.instance_key_slug or "dbaas"
    region = "-".join(zone.split("-")[:-1])
    provider = gcp.Provider(resource_name=zone, zone=zone)

    network = gcp.compute.Network(
        slug,
        auto_create_subnetworks=False,
        opts=pulumi.ResourceOptions(provider=provider),
    )
    subnet = gcp.compute.Subnetwork(
        f"{slug}-client",
        network=network.id,
        region=region,
        ip_cidr_range=CLIENT_SUBNET_CIDR,
        opts=pulumi.ResourceOptions(provider=provider),
    )
    gcp.compute.Firewall(
        f"{slug}-allow-internal",
        network=network.id,
        source_ranges=["10.0.0.0/8"],
        allows=[
            gcp.compute.FirewallAllowArgs(protocol="tcp"),
            gcp.compute.FirewallAllowArgs(protocol="udp"),
            gcp.compute.FirewallAllowArgs(protocol="icmp"),
        ],
        opts=pulumi.ResourceOptions(provider=provider),
    )
    gcp.compute.Firewall(
        f"{slug}-allow-ssh",
        network=network.id,
        source_ranges=["0.0.0.0/0"],
        allows=[gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["22"])],
        opts=pulumi.ResourceOptions(provider=provider),
    )

    psa_range = gcp.compute.GlobalAddress(
        f"{slug}-psa",
        purpose="VPC_PEERING",
        address_type="INTERNAL",
        prefix_length=PSA_PREFIX_LENGTH,
        network=network.id,
        opts=pulumi.ResourceOptions(provider=provider),
    )
    psa_connection = gcp.servicenetworking.Connection(
        f"{slug}-psa",
        network=network.id,
        service="servicenetworking.googleapis.com",
        reserved_peering_ranges=[psa_range.name],
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[psa_range]),
    )

    admin_password = md.admin_password or _random_password()
    instance_name = _sql_instance_name(slug)
    tier = _cloud_sql_tier(md)

    pg_instance = gcp.sql.DatabaseInstance(
        instance_name,
        name=instance_name,
        database_version=_postgres_version(md.engine_version),
        region=region,
        deletion_protection=False,
        root_password=admin_password,
        settings=gcp.sql.DatabaseInstanceSettingsArgs(
            tier=tier,
            disk_size=md.storage_gib,
            disk_type=md.storage_type or "PD_SSD",
            disk_autoresize=False,
            ip_configuration=gcp.sql.DatabaseInstanceSettingsIpConfigurationArgs(
                ipv4_enabled=False,
                private_network=network.id,
                allocated_ip_range=psa_range.name,
                enable_private_path_for_google_cloud_services=True,
                # Private VPC clients can connect without TLS (avoids BenchBase sslmode=disable failures).
                ssl_mode="ALLOW_UNENCRYPTED_AND_ENCRYPTED",
            ),
        ),
        opts=pulumi.ResourceOptions(
            provider=provider,
            depends_on=[psa_connection],
        ),
    )

    gcp.sql.Database(
        f"{instance_name}-db",
        instance=pg_instance.name,
        name=md.database_name,
        charset="UTF8",
        collation="en_US.UTF8",
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[pg_instance]),
    )

    gcp.sql.User(
        f"{instance_name}-admin",
        instance=pg_instance.name,
        name=md.admin_login,
        password=admin_password,
        type="BUILT_IN",
        database_roles=["cloudsqlsuperuser"],
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[pg_instance]),
    )

    default_bindings = {
        "SC_DB_HOST": ("db", "fqdn"),
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
        ("db", "fqdn"): pg_instance.private_ip_address,
        ("db", "password"): admin_password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    common_instance_opts = copy.deepcopy(instance_opts)
    if public_key:
        metadata = copy.deepcopy(common_instance_opts.get("metadata", {}))
        metadata["ssh-keys"] = f"ubuntu:{public_key}"
        common_instance_opts["metadata"] = metadata
    if scheduling_opts:
        common_instance_opts["scheduling"] = gcp.compute.InstanceSchedulingArgs(**scheduling_opts)

    init = copy.deepcopy(bootdisk_init_opts)
    init["size"] = dbaas.client_disk_gib
    if dbaas.client_disk_type:
        init["type"] = dbaas.client_disk_type

    client = gcp.compute.Instance(
        f"{dbaas.client_instance}-client",
        machine_type=dbaas.client_instance,
        zone=zone,
        metadata_startup_script=pulumi.Output.from_input(client_user_data).apply(
            lambda b: base64.b64decode(b).decode("utf-8")
        ),
        boot_disk=gcp.compute.InstanceBootDiskArgs(
            initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(**init),
            **bootdisk_opts,
        ),
        network_interfaces=[
            gcp.compute.InstanceNetworkInterfaceArgs(
                subnetwork=subnet.id,
                access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()],
            )
        ],
        **common_instance_opts,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[pg_instance]),
    )

    client_private_ip = client.network_interfaces.apply(
        lambda nis: nis[0].network_ip if nis else ""
    )
    client_public_ip = client.network_interfaces.apply(
        lambda nis: nis[0].access_configs[0].nat_ip if nis and nis[0].access_configs else ""
    )

    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=[zone],
        db_fqdn=pg_instance.private_ip_address,
        db_port=5432,
        db_admin_login=md.admin_login,
        db_admin_password=pulumi.Output.secret(admin_password),
        client_private_ip=client_private_ip,
        client_public_ip=client_public_ip,
        storage_gib=md.storage_gib,
        network_mode=NETWORK_MODE,
    )
