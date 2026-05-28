from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from typing import Annotated
import click
import copy
import os
import pulumi
import ediri_vultr as vultr


DEFAULTS = {
    "tags": ("VULTR_TAGS", ["created-by:sc-runner"]),
    "instance_opts": ("VULTR_INSTANCE_OPTS", dict()),
    "provider_opts": ("VULTR_PROVIDER_OPTS", dict()),
}


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
):
    # as this function might be called multiple times, and we change the values below, we must make sure we work on copies
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

    # Validate the selected region and plan exist and are compatible.
    vultr.get_region(
        filters=[vultr.GetRegionFilterArgs(name="id", values=[region])],
        opts=pulumi.InvokeOptions(provider=provider),
    )
    plan_info = vultr.get_plan(
        filters=[vultr.GetPlanFilterArgs(name="id", values=[instance])],
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if region not in plan_info.locations:
        raise ValueError(f"Vultr plan '{instance}' is not available in region '{region}'")

    if "os_id" not in instance_opts and "image_id" not in instance_opts and "snapshot_id" not in instance_opts and "iso_id" not in instance_opts:
        os_info = vultr.get_os(
            filters=[vultr.GetOsFilterArgs(name="name", values=[os_name])],
            opts=pulumi.InvokeOptions(provider=provider),
        )
        instance_opts["os_id"] = int(os_info.id)

    # Keep tags stable and include a Name-like label for easier discovery.
    instance_opts["tags"] = [*tags, f"name:{instance}"]

    vultr.Instance(
        instance,
        region=region,
        plan=instance,
        label=instance,
        hostname=instance,
        opts=pulumi.ResourceOptions(provider=provider),
        **instance_opts,
    )
