import base64

from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_gcp as gcp


DEFAULTS = {
    "instance_opts": ("GCP_INSTANCE_OPTS", dict(labels={"created-by": "sc-runner"})),
    "bootdisk_opts": ("GCP_BOOTDISK_OPTS", dict()),
    "bootdisk_init_opts": ("GCP_BOOTDISK_INIT_OPTS", dict(image="ubuntu-2404-lts-amd64")),
    "scheduling_opts": ("GCP_SCHEDULING_OPTS", dict()),
}

def resources_gcp(
        zone: Annotated[str, DefaultOpt(["--zone"], type=click.Choice(data.zones("gcp")), help="Availability zone"), StackName()] = os.environ.get("GCP_ZONE", "us-east1-d"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("gcp")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "e2-micro"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        instance_opts: Annotated[str, DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi gcp.compute.Instance options")] = default(DEFAULTS, "instance_opts"),
        bootdisk_opts: Annotated[str, DefaultOpt(["--bootdisk-opts"], type=JSON, default=defaults(DEFAULTS, "bootdisk_opts"), help="Pulumi gcp.compute.InstanceBootDiskArgs options")] = default(DEFAULTS, "bootdisk_opts"),
        bootdisk_init_opts: Annotated[str, DefaultOpt(["--bootdisk-init-opts"], type=JSON, default=defaults(DEFAULTS, "bootdisk_init_opts"), help="Pulumi gcp.compute.InstanceBootDiskInitializeParamsArgs options")] = default(DEFAULTS, "bootdisk_init_opts"),
        scheduling_opts: Annotated[str, DefaultOpt(["--scheduling-opts"], type=JSON, default=defaults(DEFAULTS, "scheduling_opts"), help="Pulumi gcp.compute.InstanceSchedulingArgs options")] = default(DEFAULTS, "scheduling_opts"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
):
    if "zone" in instance_opts:
        # as zone is part of the Pulumi stack name, it must be specified in the zone option and not in instance_opts
        raise ValueError("zone must be specified in the zone option")
    # we don't want to modify the default
    instance_opts = copy.deepcopy(instance_opts)
    if user_data:
        instance_opts["metadata_startup_script"] = base64.b64decode(user_data)
    if disk_size:
        bootdisk_init_opts["size"] = disk_size

    provider = gcp.Provider(
        resource_name=zone,
        zone=zone,
    )
    if public_key:
        if "metadata" in instance_opts:
            instance_opts["metadata"]["ssh-keys"] = f"ubuntu:{public_key}"
        else:
            instance_opts["metadata"] = {"ssh-keys": f"ubuntu:{public_key}"}
    instance_opts |= dict(
        machine_type=instance,
        zone=zone,
        boot_disk=gcp.compute.InstanceBootDiskArgs(
            initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(**bootdisk_init_opts),
            **bootdisk_opts,
        ),
        network_interfaces=[
            gcp.compute.InstanceNetworkInterfaceArgs(
                network="default",
                access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()]
            )
        ],
    )
    if scheduling_opts:
        instance_opts["scheduling"] = gcp.compute.InstanceSchedulingArgs(**scheduling_opts)
    gcp.compute.Instance(
        instance,
        **instance_opts,
        opts=pulumi.ResourceOptions(provider=provider),
    )