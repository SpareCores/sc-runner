import base64
import copy
import os
import zlib
from typing import Annotated

import click
import pulumi
import pulumi_upcloud as upcloud

from .. import JSON, DefaultOpt, data
from .base import StackName, default, defaults, ensure_spot_supported, spot_from_env, spot_opt
from .managed_db import DbaasStackSpec
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack

DEFAULTS = {
    "instance_opts": (
        "UPCLOUD_INSTANCE_OPTS",
        dict(
            labels={"created-by": "sc-runner"},
            # tags=["sc-runner"],  # only main account can set tags
        ),
    ),
}


def user_data_plaintext(user_data_b64: pulumi.Input[str]) -> pulumi.Output[str]:
    """UpCloud Server.user_data wants the script body, not base64.

    Plain inspector starts already pass plaintext; DBaaS/multi-VM build
    base64 via ``build_user_data_b64`` and must decode before attach.
    """
    return pulumi.Output.from_input(user_data_b64).apply(
        lambda b: base64.b64decode(b).decode("utf-8") if b else ""
    )


def private_cidr_for_slug(slug: str) -> tuple[str, str]:
    """Deterministic RFC1918 /24 + gateway for a private network slug.

    UpCloud rejects overlapping private network addresses account-wide (not
    per-zone), so concurrent stacks cannot all use 10.0.1.0/24.
    """
    h = zlib.crc32(slug.encode()) & 0xFFFFFFFF
    # 10.{64-127}.{0-255}.0/24
    second = 64 + (h % 64)
    third = (h // 64) % 256
    cidr = f"10.{second}.{third}.0/24"
    gateway = f"10.{second}.{third}.1"
    return cidr, gateway


def resources_upcloud(
    region: Annotated[
        str,
        DefaultOpt(
            ["--region"], type=click.Choice(data.regions("upcloud")), help="Region"
        ),
        StackName(),
    ] = os.environ.get("UPCLOUD_REGION", "fi-hel1"),
    instance: Annotated[
        str,
        DefaultOpt(
            ["--instance"],
            type=click.Choice(data.servers("upcloud")),
            help="Server plan",
        ),
        StackName(),
    ] = os.environ.get("INSTANCE_TYPE", "DEV-1xCPU-4GB"),
    public_key: Annotated[
        str,
        DefaultOpt(["--public-key"], type=str, help="SSH public key for the root user"),
    ] = os.environ.get("SSH_PUBLIC_KEY", ""),
    user_data: Annotated[
        str | None,
        DefaultOpt(
            ["--user-data"],
            type=str,
            help="Base64 encoded string with user_data script to run at boot",
        ),
    ] = os.environ.get("USER_DATA", None),
    disk_size: Annotated[
        int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")
    ] = int(os.environ.get("DISK_SIZE", 30)),
    instance_opts: Annotated[
        str,
        DefaultOpt(
            ["--instance-opts"],
            type=JSON,
            default=defaults(DEFAULTS, "instance_opts"),
            help="pulumi_upcloud.Server options",
        ),
    ] = default(DEFAULTS, "instance_opts"),
    spot: Annotated[bool, spot_opt()] = spot_from_env(),
    dbaas_slug: Annotated[
        str | None,
        DefaultOpt(["--dbaas-slug"], type=str, help="DBaaS stack slug (cache-tier provision)"),
        StackName(),
    ] = os.environ.get("DBAAS_SLUG", None),
    multi_vm: MultiVmStackSpec | None = None,
    dbaas: DbaasStackSpec | None = None,
):
    ensure_spot_supported("upcloud", spot)
    if dbaas is not None:
        from .upcloud_dbaas import resources_upcloud_dbaas

        return resources_upcloud_dbaas(
            region=region,
            public_key=public_key,
            instance_opts=instance_opts,
            dbaas=dbaas,
        )
    if multi_vm is not None:
        return resources_upcloud_multi(
            region=region,
            public_key=public_key,
            instance_opts=instance_opts,
            multi_vm=multi_vm,
        )
    # we don't want to modify the default
    instance_opts = copy.deepcopy(instance_opts)
    upcloud.Server(
        instance,
        hostname=instance.lower(),
        plan=instance,
        zone=region,
        login={"user": "root", "keys": [public_key], "create_password": False},
        template={
            "size": disk_size,
            "storage": "Ubuntu Server 24.04 LTS (Noble Numbat)",
        },
        network_interfaces=[{"type": "public"}],
        metadata=True,
        user_data=user_data,
        **instance_opts,
    )


def resources_upcloud_multi(
    *,
    region: str,
    public_key: str,
    instance_opts: dict,
    multi_vm: MultiVmStackSpec,
):
    instance_opts = copy.deepcopy(instance_opts)
    private_cidr, gateway = private_cidr_for_slug(
        f"{multi_vm.client_instance}-{multi_vm.db_instance}"
    )

    router = upcloud.Router(
        multi_vm.db_instance,
        name=f"{multi_vm.db_instance}-router",
    )
    network = upcloud.Network(
        multi_vm.db_instance,
        name=f"{multi_vm.db_instance}-private",
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

    def vm_opts(plan: str, user_data_b64: pulumi.Input[str], disk_gib: int):
        opts = copy.deepcopy(instance_opts)
        opts.update(
            dict(
                hostname=plan.lower(),
                plan=plan,
                zone=region,
                login={"user": "root", "keys": [public_key], "create_password": False},
                template={"size": disk_gib, "storage": "Ubuntu Server 24.04 LTS (Noble Numbat)"},
                network_interfaces=[
                    {"type": "public"},
                    {"type": "private", "network": network.id},
                ],
                metadata=True,
                user_data=user_data_plaintext(user_data_b64),
            )
        )
        return opts

    client = upcloud.Server(
        f"{multi_vm.client_instance}-client",
        **vm_opts(multi_vm.client_instance, multi_vm.client_user_data_b64, multi_vm.client_disk_gib),
    )
    client_private_ip = client.network_interfaces.apply(
        lambda ifaces: next((i.ip_address for i in ifaces if i.type == "private"), "")
    )

    server_user_data_b64 = build_server_user_data_b64(multi_vm, client_private_ip)
    server = upcloud.Server(
        multi_vm.db_instance,
        **vm_opts(multi_vm.db_instance, server_user_data_b64, multi_vm.db_disk_gib),
        opts=pulumi.ResourceOptions(depends_on=[client]),
    )

    def public_ip(server_obj):
        return server_obj.network_interfaces.apply(
            lambda ifaces: next((i.ip_address for i in ifaces if i.type == "public"), "")
        )

    def private_ip(server_obj):
        return server_obj.network_interfaces.apply(
            lambda ifaces: next((i.ip_address for i in ifaces if i.type == "private"), "")
        )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=private_ip(server),
        client_private_ip=client_private_ip,
        db_public_ip=public_ip(server),
        client_public_ip=public_ip(client),
        region=region,
        zones=pulumi.Output.all(client.zone, server.zone).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )
