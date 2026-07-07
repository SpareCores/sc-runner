"""Azure Flexible Server + companion benchmark VM in one Pulumi stack."""

from __future__ import annotations

import secrets
import string

import pulumi
from pulumi_azure_native.compute import (
    HardwareProfileArgs,
    ImageReferenceArgs,
    LinuxConfigurationArgs,
    ManagedDiskParametersArgs,
    NetworkInterfaceReferenceArgs,
    NetworkProfileArgs,
    OSDiskArgs,
    OSProfileArgs,
    SshConfigurationArgs,
    SshPublicKeyArgs,
    StorageProfileArgs,
    VirtualMachine,
)
from pulumi_azure_native.dbforpostgresql import Database, Server
from pulumi_azure_native.dbforpostgresql._inputs import NetworkArgs, SkuArgs, StorageArgs
from pulumi_azure_native.network import (
    DelegationArgs,
    IPAllocationMethod,
    NetworkInterface,
    NetworkInterfaceIPConfigurationArgs,
    PublicIPAddress,
    PublicIPAddressArgs,
    Subnet,
    SubnetArgs,
    VirtualNetwork,
)
from pulumi_azure_native.privatedns import PrivateZone, VirtualNetworkLink
from pulumi_azure_native.privatedns._inputs import SubResourceArgs
from pulumi_azure_native.resources import ResourceGroup

from .. import data
from .managed_db import DbaasStackSpec
from .multi_vm import VmSpec, build_user_data_b64

DEFAULT_STORAGE_ACCOUNT_TYPE = "Standard_LRS"
PG_PRIVATE_DNS_ZONE = "privatelink.postgres.database.azure.com"
PG_DNS_LOCATION = "global"
PG_SUBNET_PREFIX = "10.0.2.0/24"
NETWORK_MODE = "private_vnet"

# Base provisioned IOPS and throughput (MB/s) per Premium SSD performance tier.
_PREMIUM_DISK_PERF: dict[str, tuple[int, int]] = {
    "P1": (120, 25),
    "P2": (120, 25),
    "P3": (120, 25),
    "P4": (120, 25),
    "P6": (240, 50),
    "P10": (500, 100),
    "P15": (1100, 125),
    "P20": (2300, 150),
    "P30": (5000, 200),
    "P40": (7500, 250),
    "P50": (7500, 250),
    "P60": (16000, 500),
    "P70": (18000, 750),
    "P80": (20000, 900),
}


def _pg_storage_args(md) -> StorageArgs:
    """Build Flexible Server storage args for Premium_LRS vs PremiumV2_LRS."""
    if md.storage_type in {"PremiumV2_LRS", "UltraSSD_LRS"}:
        iops, throughput = _PREMIUM_DISK_PERF[md.storage_iops_tier]
        return StorageArgs(
            storage_size_gb=md.storage_gib,
            type=md.storage_type,
            iops=iops,
            throughput=throughput,
        )
    return StorageArgs(
        storage_size_gb=md.storage_gib,
        type=md.storage_type or "Premium_LRS",
        tier=md.storage_iops_tier,
    )


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def export_dbaas_stack(
    *,
    spec: DbaasStackSpec,
    region: pulumi.Input[str],
    zones: pulumi.Input[list[str]],
    db_fqdn: pulumi.Input[str],
    db_port: int,
    db_admin_login: str,
    db_admin_password: pulumi.Input[str],
    client_private_ip: pulumi.Input[str],
    client_public_ip: pulumi.Input[str],
    storage_gib: int,
) -> None:
    """Export stack outputs consumed by sc-inspector user-data."""
    md = spec.managed_db
    pulumi.export("topology", spec.topology)
    pulumi.export("region", region)
    pulumi.export("zones", zones)
    pulumi.export("client_instance", spec.client_instance)
    pulumi.export("client_private_ip", client_private_ip)
    pulumi.export("client_public_ip", client_public_ip)
    pulumi.export("db_fqdn", db_fqdn)
    pulumi.export("db_port", db_port)
    pulumi.export("db_admin_login", db_admin_login)
    pulumi.export("db_admin_password", db_admin_password)
    pulumi.export("db_name", md.database_name)
    pulumi.export("native_id", md.native_id)
    pulumi.export("engine_version", md.engine_version)
    pulumi.export("ha_mode", md.ha_mode)
    pulumi.export("storage_gib", storage_gib)
    pulumi.export("storage_edition", md.storage_edition)
    pulumi.export("iops_tier", md.storage_iops_tier)
    pulumi.export("network_mode", NETWORK_MODE)
    for key, value in spec.extra_exports.items():
        pulumi.export(key, value)


def resources_azure_dbaas(
    *,
    region: str,
    zone: str | None,
    image_publisher: str,
    image_offer: str,
    image_sku: str | None,
    image_version: str,
    public_key: str,
    tags: dict,
    vnet_opts: dict,
    subnet_opts: dict,
    publicip_opts: dict,
    dbaas: DbaasStackSpec,
) -> None:
    """Provision Azure Flexible Server in a VNet with private DNS + client VM."""
    md = dbaas.managed_db
    if image_sku is None:
        arch = data.server_cpu_architecture("azure", dbaas.client_instance).lower()
        image_sku = "server-arm64" if "arm" in arch else "server"

    slug = dbaas.instance_key_slug or "dbaas"
    res_name = f"{region}{zone or ''}{slug}"
    resource_group = ResourceGroup(
        slug,
        location=region,
        resource_group_name=res_name,
        tags=tags,
    )
    vnet = VirtualNetwork(
        slug,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **vnet_opts,
    )

    private_zone = PrivateZone(
        f"{slug}-pg-dns",
        resource_group_name=resource_group.name,
        private_zone_name=PG_PRIVATE_DNS_ZONE,
        location=PG_DNS_LOCATION,
        tags=tags,
    )
    VirtualNetworkLink(
        f"{slug}-pg-dns-link",
        resource_group_name=resource_group.name,
        private_zone_name=private_zone.name,
        location=PG_DNS_LOCATION,
        virtual_network=SubResourceArgs(id=vnet.id),
        registration_enabled=False,
        virtual_network_link_name=f"{slug}-vnet-link",
    )

    client_subnet = Subnet(
        f"{slug}-client",
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        subnet_name="client",
        **subnet_opts,
    )
    pg_subnet = Subnet(
        f"{slug}-pg",
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        subnet_name="pg",
        address_prefix=PG_SUBNET_PREFIX,
        delegations=[
            DelegationArgs(
                name="pg-delegation",
                service_name="Microsoft.DBforPostgreSQL/flexibleServers",
            )
        ],
    )

    admin_password = md.admin_password or _random_password()
    server_name = f"sc-{slug}"[:63].rstrip("-")

    pg_server = Server(
        server_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        server_name=server_name,
        version=md.engine_version,
        sku=SkuArgs(name=md.sku_name, tier=md.sku_tier),
        storage=_pg_storage_args(md),
        administrator_login=md.admin_login,
        administrator_login_password=admin_password,
        availability_zone=zone,
        network=NetworkArgs(
            delegated_subnet_resource_id=pg_subnet.id,
            private_dns_zone_arm_resource_id=private_zone.id,
        ),
        tags=tags,
        opts=pulumi.ResourceOptions(depends_on=[pg_subnet, private_zone]),
    )

    Database(
        f"{server_name}-db",
        resource_group_name=resource_group.name,
        server_name=pg_server.name,
        database_name=md.database_name,
        charset="UTF8",
        collation="en_US.utf8",
        opts=pulumi.ResourceOptions(depends_on=[pg_server]),
    )

    client_name = f"{dbaas.client_instance}-client"
    client_public_ip = PublicIPAddress(
        client_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **publicip_opts,
    )
    client_nic = NetworkInterface(
        client_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        ip_configurations=[
            NetworkInterfaceIPConfigurationArgs(
                name=client_name,
                subnet=SubnetArgs(id=client_subnet.id),
                private_ip_allocation_method=IPAllocationMethod.DYNAMIC,
                public_ip_address=PublicIPAddressArgs(id=client_public_ip.id),
            )
        ],
        tags=tags,
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
        ("db", "fqdn"): pg_server.fully_qualified_domain_name,
        ("db", "password"): admin_password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    client_vmopts = dict(
        resource_group_name=resource_group.name,
        location=resource_group.location,
        network_profile=NetworkProfileArgs(
            network_interfaces=[NetworkInterfaceReferenceArgs(id=client_nic.id)]
        ),
        hardware_profile=HardwareProfileArgs(vm_size=dbaas.client_instance),
        os_profile=OSProfileArgs(
            computer_name="sc-dbaas-client",
            admin_username="ubuntu",
            linux_configuration=LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=SshConfigurationArgs(
                    public_keys=[
                        SshPublicKeyArgs(
                            key_data=public_key,
                            path="/home/ubuntu/.ssh/authorized_keys",
                        )
                    ]
                ),
            ),
            custom_data=client_user_data,
        ),
        storage_profile=StorageProfileArgs(
            os_disk=OSDiskArgs(
                create_option="FromImage",
                managed_disk=ManagedDiskParametersArgs(
                    storage_account_type=dbaas.client_disk_type or DEFAULT_STORAGE_ACCOUNT_TYPE
                ),
                caching="ReadWrite",
                disk_size_gb=dbaas.client_disk_gib,
            ),
            image_reference=ImageReferenceArgs(
                publisher=image_publisher,
                offer=image_offer,
                sku=image_sku,
                version=image_version,
            ),
        ),
        tags=tags,
    )
    if zone is not None:
        client_vmopts["zones"] = [zone]
    client_vm = VirtualMachine(
        client_name,
        opts=pulumi.ResourceOptions(depends_on=[pg_server]),
        **client_vmopts,
    )

    client_private_ip = client_nic.ip_configurations.apply(
        lambda ipcs: ipcs[0].private_ip_address if ipcs and ipcs[0] else ""
    )
    client_public_ip_addr = client_public_ip.ip_address

    zones = client_vm.zones.apply(
        lambda zs: [(zs[0] if isinstance(zs, list) and zs else zs)]
        if zs is not None
        else [zone]
    )
    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=zones,
        db_fqdn=pg_server.fully_qualified_domain_name,
        db_port=5432,
        db_admin_login=md.admin_login,
        db_admin_password=admin_password,
        client_private_ip=client_private_ip,
        client_public_ip=client_public_ip_addr,
        storage_gib=md.storage_gib,
    )
