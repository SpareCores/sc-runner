import base64
import os
from typing import Annotated

import click
import pulumi_ovh as ovh
import pulumi
from pulumi import CustomTimeouts, ResourceOptions

from .. import JSON, DefaultOpt, data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack

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
    multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_ovh_multi(
            project_id=project_id,
            region=region,
            image_name=image_name,
            instance_opts=instance_opts,
            multi_vm=multi_vm,
        )
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
        # OVH default timeout is 1 hour that is overkill, so decrease to 10 mins (like AWS default)
        opts=ResourceOptions(custom_timeouts=CustomTimeouts(create="10m")),
        **instance_opts,
    )


def resources_ovh_multi(
    *,
    project_id: str,
    region: str,
    image_name: str,
    instance_opts: dict,
    multi_vm: MultiVmStackSpec,
):
    flavors = ovh.cloudproject.get_flavors(service_name=project_id)
    db_flavor_id = find_resource_id(flavors.flavors, multi_vm.db_instance, "instance type", region)
    client_flavor_id = find_resource_id(flavors.flavors, multi_vm.client_instance, "instance type", region)
    images = ovh.cloudproject.get_images(service_name=project_id)
    image_id = find_resource_id(images.images, image_name, "image", region)

    private_network = ovh.cloudproject.NetworkPrivate(
        multi_vm.db_instance,
        service_name=project_id,
        name=f"sc-runner-{multi_vm.db_instance}",
        regions=[region],
    )
    subnet = ovh.cloudproject.NetworkPrivateSubnet(
        multi_vm.db_instance,
        service_name=project_id,
        network_id=private_network.id,
        region=region,
        network="10.0.1.0/24",
        start="10.0.1.10",
        end="10.0.1.250",
        dhcp=True,
    )
    private_network_id = private_network.regions_openstack_ids.apply(lambda ids: ids.get(region, ""))

    client = ovh.cloudproject.Instance(
        f"{multi_vm.client_instance}-client",
        service_name=project_id,
        name=f"{multi_vm.client_instance}-client",
        boot_from={"image_id": image_id},
        flavor={"flavor_id": client_flavor_id},
        network={
            "public": True,
            "private": {
                "network": {
                    "id": private_network_id,
                    "subnet_id": subnet.id,
                }
            },
        },
        billing_period="hourly",
        region=region,
        user_data=multi_vm.client_user_data_b64,
        opts=ResourceOptions(custom_timeouts=CustomTimeouts(create="10m")),
        **instance_opts,
    )

    def instance_private_ip(instance_obj):
        return instance_obj.addresses.apply(
            lambda addrs: next((a.ip for a in addrs if a.version == 4 and not a.public), "")
        )

    def instance_public_ip(instance_obj):
        return instance_obj.addresses.apply(
            lambda addrs: next((a.ip for a in addrs if a.version == 4 and a.public), "")
        )

    server_user_data_b64 = build_server_user_data_b64(multi_vm, instance_private_ip(client))
    server = ovh.cloudproject.Instance(
        multi_vm.db_instance,
        service_name=project_id,
        name=multi_vm.db_instance,
        boot_from={"image_id": image_id},
        flavor={"flavor_id": db_flavor_id},
        network={
            "public": True,
            "private": {
                "network": {
                    "id": private_network_id,
                    "subnet_id": subnet.id,
                }
            },
        },
        billing_period="hourly",
        region=region,
        user_data=server_user_data_b64,
        opts=ResourceOptions(custom_timeouts=CustomTimeouts(create="10m"), depends_on=[client]),
        **instance_opts,
    )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=instance_private_ip(server),
        client_private_ip=instance_private_ip(client),
        db_public_ip=instance_public_ip(server),
        client_public_ip=instance_public_ip(client),
        region=region,
        zones=pulumi.Output.all(client.availability_zone, server.availability_zone).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )
