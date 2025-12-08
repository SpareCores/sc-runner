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


def find_resource_id(items, name: str, resource_type: str, region: str) -> str:
    """Find a resource ID by name and region."""
    resource_id = next(
        (item.id for item in items if item.name == name and item.region == region),
        None,
    )
    if not resource_id:
        raise ValueError(
            f"The `{name}` {resource_type} is not supported in the `{region}` region"
        )
    return resource_id


def resources_ovh(
    project_id: Annotated[
        str,
        DefaultOpt(
            ["--project-id"],
            type=str,
            help="OVHcloud project UUID",
            required=True,
            # don't use envvar Click parameter here for the default value
            # as it's not picked up when using the runner.create() instead of the CLI
        ),
    ] = os.environ.get("OVH_CLOUD_PROJECT_SERVICE"),
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
    image_name: Annotated[
        str, DefaultOpt(["--image-name"], type=str, help="Boot image name")
    ] = "Ubuntu 24.04",
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
    """Define an OVH cloud instance.

    Required environment variables/configuration:

    - `OVH_CLOUD_PROJECT_SERVICE` (OVHcloud project UUID)
    - `OVH_ENDPOINT` (e.g. ovh-eu)
    - `OVH_CLIENT_ID`
    - `OVH_CLIENT_SECRET`

    Required permissions:

    - `publicCloudProject:apiovh:operation/get`
    - `publicCloudProject:apiovh:flavor/get`
    - `publicCloudProject:apiovh:image/get`
    - `publicCloudProject:apiovh:instance/create`
    - `publicCloudProject:apiovh:region/instance/create`
    - `publicCloudProject:apiovh:region/instance/get`
    - `publicCloudProject:apiovh:instance/delete`

    Required scopes:

    - OVH account
    - OVH project
    """
    if user_data:
        instance_opts["user_data"] = base64.b64encode(user_data.encode()).decode()

    flavors = ovh.cloudproject.get_flavors(service_name=project_id)
    flavor_id = find_resource_id(flavors.flavors, instance, "instance type", region)

    images = ovh.cloudproject.get_images(service_name=project_id)
    image_id = find_resource_id(images.images, image_name, "image", region)

    ovh.cloudproject.Instance(
        instance,
        name=instance,
        boot_from={"image_id": image_id},
        flavor={"flavor_id": flavor_id},
        network={"public": True},
        billing_period="hourly",
        region=region,
        **instance_opts,
    )
