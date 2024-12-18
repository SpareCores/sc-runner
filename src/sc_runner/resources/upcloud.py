import copy
import os
from typing import Annotated

import click
import pulumi_upcloud as upcloud

from .. import JSON, DefaultOpt, data
from .base import StackName, default, defaults

DEFAULTS = {
    "instance_opts": (
        "UPCLOUD_INSTANCE_OPTS",
        dict(
            labels={"created-by": "sc-runner"},
            # tags=["sc-runner"],  # only main account can set tags
        ),
    ),
}


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
):
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
