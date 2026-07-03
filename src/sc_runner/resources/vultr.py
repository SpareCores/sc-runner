from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
from functools import lru_cache
from typing import Annotated
import click
import copy
import os
import pulumi
import ediri_vultr as vultr
from sc_crawler.tables import Server
from sqlmodel import select


DEFAULTS = {
    "tags": ("VULTR_TAGS", ["created-by:sc-runner"]),
    "instance_opts": ("VULTR_INSTANCE_OPTS", dict()),
    "provider_opts": ("VULTR_PROVIDER_OPTS", dict()),
}


@lru_cache
def _is_bare_metal(plan: str) -> bool:
    family = data.session.exec(
        select(Server.family)
        .where(Server.vendor_id == "vultr")
        .where(Server.api_reference == plan)
    ).one()
    return family.startswith("Bare Metal")


def resolve_plan(instance: str, disk_size: int) -> str:
    """Return a deployable Vultr plan id, remapping block-only VX1 tiers when needed."""
    row = data.session.exec(
        select(Server)
        .where(Server.vendor_id == "vultr")
        .where(Server.api_reference == instance)
    ).one()
    if row.storage_size > 1:
        return instance
    candidates = data.session.exec(
        select(Server.api_reference, Server.storage_size)
        .where(Server.vendor_id == "vultr")
        .where(Server.family == row.family)
        .where(Server.vcpus == row.vcpus)
        .where(Server.memory_amount == row.memory_amount)
        .where(Server.storage_size > 1)
        .where(Server.status == "ACTIVE")
        .order_by(Server.storage_size)
    ).all()
    if not candidates:
        raise ValueError(
            f"Vultr plan '{instance}' requires block storage and no ACTIVE sibling plan "
            f"exists in sc-data for family={row.family!r}"
        )
    for api_reference, storage_size in candidates:
        if storage_size >= disk_size:
            return api_reference
    return candidates[-1][0]


def resources_vultr(
    region: Annotated[
        str,
        DefaultOpt(["--region"], type=click.Choice(data.regions("vultr")), help="Region"),
        StackName(),
    ] = os.environ.get("VULTR_REGION", "ewr"),
    instance: Annotated[
        str,
        DefaultOpt(["--instance"], type=click.Choice(data.servers("vultr")), help="Instance type/plan"),
        StackName(),
    ] = os.environ.get("INSTANCE_TYPE", "vc2-1c-1gb"),
    public_key: Annotated[
        str,
        DefaultOpt(["--public-key"], type=str, help="SSH public key"),
    ] = os.environ.get("SSH_PUBLIC_KEY", ""),
    tags: Annotated[
        str,
        DefaultOpt(["--tags"], type=JSON, default=defaults(DEFAULTS, "tags"), help="Tags for created resources"),
    ] = default(DEFAULTS, "tags"),
    instance_opts: Annotated[
        str,
        DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi vultr.Instance options"),
    ] = default(DEFAULTS, "instance_opts"),
    provider_opts: Annotated[
        str,
        DefaultOpt(["--provider-opts"], type=JSON, default=defaults(DEFAULTS, "provider_opts"), help="Pulumi vultr.Provider options"),
    ] = default(DEFAULTS, "provider_opts"),
    os_name: Annotated[
        str,
        DefaultOpt(["--os-name"], type=str, help="Vultr OS name to install"),
    ] = os.environ.get("VULTR_OS_NAME", "Ubuntu 24.04 LTS x64"),
    user_data: Annotated[
        str | None,
        DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot"),
    ] = os.environ.get("USER_DATA", None),
    disk_size: Annotated[
        int,
        DefaultOpt(["--disk-size"], type=int, help="Minimum bundled storage in GiB for block-only VX1 plans"),
    ] = int(os.environ.get("DISK_SIZE", 30)),
    multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_vultr_multi(
            region=region,
            public_key=public_key,
            tags=tags,
            instance_opts=instance_opts,
            provider_opts=provider_opts,
            os_name=os_name,
            disk_size=disk_size,
            multi_vm=multi_vm,
        )
    # as this function might be called multiple times, and we change the values below, we must make sure we work on copies
    instance_opts = copy.deepcopy(instance_opts)
    provider_opts = copy.deepcopy(provider_opts)
    tags = copy.deepcopy(tags)
    if not isinstance(tags, list):
        raise ValueError("tags must be a list of strings for Vultr (e.g. ['created-by:sc-runner'])")

    bare_metal = _is_bare_metal(instance)
    plan = instance if bare_metal else resolve_plan(instance, disk_size)
    if plan != instance:
        pulumi.log.info(f"Remapped Vultr plan {instance} -> {plan} (storage >= {disk_size} GiB)")

    provider = vultr.Provider(
        resource_name=region,
        opts=pulumi.ResourceOptions(),
        **provider_opts,
    )

    if public_key and "ssh_key_ids" not in instance_opts:
        ssh_key = vultr.SSHKey(
            instance,
            name=instance,
            ssh_key=public_key,
            opts=pulumi.ResourceOptions(provider=provider),
        )
        instance_opts["ssh_key_ids"] = [ssh_key.id]

    if user_data:
        instance_opts["user_data"] = user_data

    vultr.get_region(
        filters=[vultr.GetRegionFilterArgs(name="id", values=[region])],
        opts=pulumi.InvokeOptions(provider=provider),
    )

    if "os_id" not in instance_opts and "image_id" not in instance_opts and "snapshot_id" not in instance_opts and "iso_id" not in instance_opts:
        os_info = vultr.get_os(
            filters=[vultr.GetOsFilterArgs(name="name", values=[os_name])],
            opts=pulumi.InvokeOptions(provider=provider),
        )
        instance_opts["os_id"] = int(os_info.id)

    instance_opts["tags"] = [*tags, f"name:{instance}"]

    resource_opts = pulumi.ResourceOptions(provider=provider)
    if bare_metal:
        vultr.BareMetalServer(
            instance,
            plan=instance,
            region=region,
            label=instance,
            hostname=instance,
            opts=resource_opts,
            **instance_opts,
        )
    else:
        vultr.Instance(
            instance,
            region=region,
            plan=plan,
            label=instance,
            hostname=instance,
            opts=resource_opts,
            **instance_opts,
        )


def resources_vultr_multi(
    *,
    region: str,
    public_key: str,
    tags: list[str],
    instance_opts: dict,
    provider_opts: dict,
    os_name: str,
    disk_size: int,
    multi_vm: MultiVmStackSpec,
):
    instance_opts = copy.deepcopy(instance_opts)
    provider_opts = copy.deepcopy(provider_opts)
    tags = copy.deepcopy(tags)
    if not isinstance(tags, list):
        raise ValueError("tags must be a list of strings for Vultr (e.g. ['created-by:sc-runner'])")

    if _is_bare_metal(multi_vm.db_instance) or _is_bare_metal(multi_vm.client_instance):
        raise ValueError("multi_vm is currently supported on Vultr instances only (not bare metal)")

    provider = vultr.Provider(
        resource_name=region,
        opts=pulumi.ResourceOptions(),
        **provider_opts,
    )
    vultr.get_region(
        filters=[vultr.GetRegionFilterArgs(name="id", values=[region])],
        opts=pulumi.InvokeOptions(provider=provider),
    )
    os_info = vultr.get_os(
        filters=[vultr.GetOsFilterArgs(name="name", values=[os_name])],
        opts=pulumi.InvokeOptions(provider=provider),
    )
    vpc = vultr.Vpc(
        multi_vm.db_instance,
        region=region,
        description=f"sc-runner-{multi_vm.db_instance}",
        opts=pulumi.ResourceOptions(provider=provider),
    )
    if public_key:
        ssh_key = vultr.SSHKey(
            multi_vm.db_instance,
            name=multi_vm.db_instance,
            ssh_key=public_key,
            opts=pulumi.ResourceOptions(provider=provider),
        )
        ssh_key_ids = [ssh_key.id]
    else:
        ssh_key_ids = instance_opts.get("ssh_key_ids", [])

    def vm_opts(instance_type: str, user_data_b64: pulumi.Input[str]):
        opts = copy.deepcopy(instance_opts)
        opts["os_id"] = int(os_info.id)
        opts["user_data"] = user_data_b64
        opts["ssh_key_ids"] = ssh_key_ids
        opts["tags"] = [*tags, f"name:{instance_type}"]
        opts["vpc_ids"] = [vpc.id]
        return opts

    client_plan = resolve_plan(multi_vm.client_instance, multi_vm.client_disk_gib or disk_size)
    client = vultr.Instance(
        f"{multi_vm.client_instance}-client",
        region=region,
        plan=client_plan,
        label=f"{multi_vm.client_instance}-client",
        hostname=f"{multi_vm.client_instance}-client",
        opts=pulumi.ResourceOptions(provider=provider),
        **vm_opts(multi_vm.client_instance, multi_vm.client_user_data_b64),
    )
    server_user_data_b64 = build_server_user_data_b64(multi_vm, client.internal_ip)
    server_plan = resolve_plan(multi_vm.db_instance, multi_vm.db_disk_gib or disk_size)
    server = vultr.Instance(
        multi_vm.db_instance,
        region=region,
        plan=server_plan,
        label=multi_vm.db_instance,
        hostname=multi_vm.db_instance,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[client]),
        **vm_opts(multi_vm.db_instance, server_user_data_b64),
    )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=server.internal_ip,
        client_private_ip=client.internal_ip,
        db_public_ip=server.main_ip,
        client_public_ip=client.main_ip,
        region=region,
        zones=pulumi.Output.all(client.region, server.region).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )
