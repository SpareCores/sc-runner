import base64
import os
from typing import Annotated

import click
import pulumi_ovh as ovh

from .. import JSON, DefaultOpt, data
from .base import StackName, default, defaults

DEFAULTS = {
    "instance_opts": ("OVH_INSTANCE_OPTS", dict()),
}


def resources_ovh(
    region: Annotated[
        str,
        DefaultOpt(["--region"], type=click.Choice(data.regions("ovh")), help="Region"),
        StackName(),
    ] = os.environ.get("OVH_REGION", "EU-WEST-PAR"),
    instance: Annotated[
        str,
        DefaultOpt(
            ["--instance"],
            type=click.Choice(data.servers("ovh")),
            help="Instance type",
        ),
        StackName(),
    ] = os.environ.get("INSTANCE_TYPE", "c3-4"),
    instance_opts: Annotated[
        str,
        DefaultOpt(
            ["--instance-opts"],
            type=JSON,
            default=defaults(DEFAULTS, "instance_opts"),
            help="Pulumi ovh.cloudproject.Instance options",
        ),
    ] = default(DEFAULTS, "instance_opts"),
    user_data: Annotated[
        str | None,
        DefaultOpt(
            ["--user-data"],
            type=str,
            help="Base64 encoded string with user_data script to run at boot",
        ),
    ] = os.environ.get("USER_DATA", None),
):
    ovh.cloudproject.Instance(
        instance,
        name=instance,
        # boot_from={"image_id": "93ea90a4-da5f-48d3-8463-83f2a2449ca3"},
        flavor={"flavor_id": instance},
        region=region,
        user_data=base64.b64decode(user_data),
        **instance_opts,
    )
