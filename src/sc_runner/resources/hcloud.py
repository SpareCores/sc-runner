import base64

from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_hcloud as hcloud


DEFAULTS = {
    "instance_opts": ("HCLOUD_INSTANCE_OPTS", dict(labels={"created-by": "sc-runner"})),
}

def resources_hcloud(
        region: Annotated[str, DefaultOpt(["--region"], type=click.Choice(data.regions("hcloud")), help="Region"), StackName()] = os.environ.get("HCLOUD_REGION", "fsn1-dc14"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("hcloud")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "cx22"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        instance_opts: Annotated[str, DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi hcloud.Server options")] = default(DEFAULTS, "instance_opts"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
):
    # we don't want to modify the default
    instance_opts = copy.deepcopy(instance_opts)

    if public_key and "ssh_keys" not in instance_opts:
        ssh_key = hcloud.SshKey(
            instance,
            name=instance,
            public_key=public_key
        )
        instance_opts["ssh_keys"] = [ssh_key.id]

    hcloud.Server(
        instance,
        name=instance,
        image="ubuntu-24.04",
        server_type=instance,
        datacenter=region,
        user_data=user_data,
        **instance_opts,
    )