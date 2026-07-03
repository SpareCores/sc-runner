from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_alicloud as alicloud
from pulumi_alicloud.vpc.network import Network as VpcNetwork
from pulumi_alicloud.vpc.switch import Switch as VpcSwitch


def shared_vpc_name(region: str, name_prefix: str) -> str:
    return f"{name_prefix}-{region}"


def shared_vswitch_name(region: str, zone_id: str, name_prefix: str) -> str:
    return f"{name_prefix}-{region}-{zone_id}"


def lookup_shared_vpc_id(
    region: str, provider: alicloud.Provider, name_prefix: str
) -> str | None:
    if not name_prefix:
        return None
    networks = alicloud.vpc.get_networks(
        vpc_name=shared_vpc_name(region, name_prefix),
        status="Available",
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if networks.ids:
        return networks.ids[0]
    return None


def lookup_shared_vswitch_id(
    region: str,
    zone_id: str,
    vpc_id: str,
    provider: alicloud.Provider,
    name_prefix: str,
) -> str | None:
    if not name_prefix:
        return None
    vswitches = alicloud.vpc.get_switches(
        vpc_id=vpc_id,
        vswitch_name=shared_vswitch_name(region, zone_id, name_prefix),
        zone_id=zone_id,
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if vswitches.ids:
        return vswitches.ids[0]
    return None


DEFAULTS = {
    "tags": ("ALICLOUD_TAGS", {"Created-by": "sc-runner"}),
    "instance_opts": ("ALICLOUD_INSTANCE_OPTS", dict(
        internet_charge_type="PayByTraffic",
        internet_max_bandwidth_out=5,
        system_disk_category="cloud_auto",
    )),
    "sg_opts": ("ALICLOUD_SG_OPTS", dict()),
    "vpc_opts": ("ALICLOUD_VPC_OPTS", dict(cidr_block="172.16.0.0/12")),
    "vswitch_opts": ("ALICLOUD_VSWITCH_OPTS", dict(cidr_block="172.16.0.0/21")),
}


def cleanup_regions(
    instance: str,
    regions: list[str],
    zones: list[str],
    zone_to_region: dict[str, str],
) -> list[str]:
    """Regions to scan when destroying stacks (catalog + zones + plan pricing)."""
    from_zones = [zone_to_region[z] for z in zones if z in zone_to_region]
    plan_regions = data.plan_regions("alicloud", instance)
    return list(dict.fromkeys([*regions, *from_zones, *plan_regions]))


def resources_alicloud(
        region: Annotated[str, DefaultOpt(["--region"], type=click.Choice(data.regions("alicloud")), help="Region"), StackName()] = os.environ.get("ALIBABA_CLOUD_REGION", "us-west-1"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("alicloud")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "ecs.t5-lc1m1.small"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        tags: Annotated[str, DefaultOpt(["--tags"], type=JSON, default=defaults(DEFAULTS, "tags"), help="Tags for created resources")] = default(DEFAULTS, "tags"),
        instance_opts: Annotated[str, DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi alicloud.ecs.Instance options")] = default(DEFAULTS, "instance_opts"),
        sg_opts: Annotated[str, DefaultOpt(["--sg-opts"], type=JSON, default=defaults(DEFAULTS, "sg_opts"), help="Pulumi alicloud.ecs.SecurityGroup options")] = default(DEFAULTS, "sg_opts"),
        vpc_opts: Annotated[str, DefaultOpt(["--vpc-opts"], type=JSON, default=defaults(DEFAULTS, "vpc_opts"), help="Pulumi alicloud.vpc.Network options")] = default(DEFAULTS, "vpc_opts"),
        vswitch_opts: Annotated[str, DefaultOpt(["--vswitch-opts"], type=JSON, default=defaults(DEFAULTS, "vswitch_opts"), help="Pulumi alicloud.vpc.Switch options")] = default(DEFAULTS, "vswitch_opts"),
        image_name: Annotated[str, DefaultOpt(["--image-name"], type=str, help="Image name regex")] = os.environ.get("ALICLOUD_IMAGE_NAME", "^ubuntu_24_04.*20G"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
        availability_zone: Annotated[str | None, DefaultOpt(["--availability-zone"], type=click.Choice(data.zones("alicloud")), help="Availability zone")] = os.environ.get("ALICLOUD_AVAILABILITY_ZONE", None),
        shared_vpc_name_prefix: Annotated[str, DefaultOpt(["--shared-vpc-name-prefix"], type=str, help="Lookup shared VPC/VSwitch as {prefix}-{region} and {prefix}-{region}-{zone}; create dedicated resources if missing")] = os.environ.get("ALICLOUD_SHARED_VPC_NAME_PREFIX", ""),
        multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_alicloud_multi(
            region=region,
            public_key=public_key,
            tags=tags,
            instance_opts=instance_opts,
            sg_opts=sg_opts,
            vpc_opts=vpc_opts,
            vswitch_opts=vswitch_opts,
            image_name=image_name,
            availability_zone=availability_zone,
            shared_vpc_name_prefix=shared_vpc_name_prefix,
            multi_vm=multi_vm,
        )
    # as this function might be called multiple times, and we change the values below, we must make sure we work on copies
    instance_opts = copy.deepcopy(instance_opts)
    sg_opts = copy.deepcopy(sg_opts)
    vpc_opts = copy.deepcopy(vpc_opts)
    vswitch_opts = copy.deepcopy(vswitch_opts)

    provider = alicloud.Provider(
        resource_name=region,
        region=region,
    )

    # Get architecture for image selection
    arch = data.server_cpu_architecture("alicloud", instance).lower().replace("i386", "x86_64")
    if "arm" in arch:
        arch = "arm64"
    else:
        arch = "x86_64"

    # Get Ubuntu image
    if "image_id" not in instance_opts:
        # NOTE: The Pulumi Alicloud provider has a bug where the architecture filter
        # only accepts "i386" or "x86_64", but not "arm64". The error message is:
        # "expected architecture to be one of [i386 x86_64], got arm64 ()"
        # So we fetch all images without the architecture filter and filter in Python.
        images = alicloud.ecs.get_images(
            owners="system",
            name_regex=image_name,
            instance_type=instance,
            most_recent=True,
            opts=pulumi.InvokeOptions(provider=provider),
        )
        # Filter images by architecture in Python since the provider doesn't support arm64 filter
        filtered_images = [img for img in images.images if img.architecture == arch]
        if not filtered_images:
            raise ValueError(f"No image found matching {image_name} for architecture {arch}")
        instance_opts["image_id"] = filtered_images[0].id

    vpc_id = sg_opts.get("vpc_id") or instance_opts.get("vpc_id")
    vswitch_id = instance_opts.get("vswitch_id")

    if availability_zone:
        zone_id = availability_zone
    else:
        # Prefer a zone that supports the selected instance type + image pair.
        # This avoids later creation failures after image selection succeeds.
        instance_types = alicloud.ecs.get_instance_types(
            instance_type=instance,
            image_id=instance_opts["image_id"],
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if (
            instance_types.instance_types
            and instance_types.instance_types[0].availability_zones
        ):
            zone_id = instance_types.instance_types[0].availability_zones[0]
        else:
            # Fallback to any zone that supports VSwitch creation.
            zones_data = alicloud.get_zones(
                available_resource_creation="VSwitch",
                opts=pulumi.InvokeOptions(provider=provider),
            )
            if not zones_data.zones:
                raise ValueError(f"No zones available for VSwitch creation in region {region}")
            zone_id = zones_data.zones[0].id

    shared_vpc_id = lookup_shared_vpc_id(region, provider, shared_vpc_name_prefix)
    if not vpc_id:
        if shared_vpc_id:
            vpc_id = shared_vpc_id
        else:
            created_vpc = VpcNetwork(
                instance,
                vpc_name=f"sc-runner-{instance}",
                opts=pulumi.ResourceOptions(provider=provider),
                **vpc_opts,
            )
            vpc_id = created_vpc.id

    if not vswitch_id:
        if shared_vpc_id and vpc_id == shared_vpc_id:
            vswitch_id = lookup_shared_vswitch_id(
                region, zone_id, vpc_id, provider, shared_vpc_name_prefix
            )
        if not vswitch_id:
            vswitch_opts["vpc_id"] = vpc_id
            vswitch_opts["zone_id"] = zone_id

            created_vswitch = VpcSwitch(
                instance,
                vswitch_name=f"sc-runner-{instance}",
                opts=pulumi.ResourceOptions(provider=provider),
                **vswitch_opts,
            )
            vswitch_id = created_vswitch.id

    # Create key pair if public key is provided
    if public_key and "key_name" not in instance_opts:
        key_pair = alicloud.ecs.EcsKeyPair(
            instance,
            key_pair_name=instance,
            public_key=public_key,
            opts=pulumi.ResourceOptions(provider=provider),
        )
        instance_opts["key_name"] = key_pair.key_pair_name

    # Create security group with allow-all rules
    if vpc_id:
        sg_opts["vpc_id"] = vpc_id
    sg = alicloud.ecs.SecurityGroup(
        instance,
        security_group_name=instance,
        description="Security group created by sc-runner",
        opts=pulumi.ResourceOptions(provider=provider),
        **sg_opts,
    )

    # Add ingress rules (allow all)
    alicloud.ecs.SecurityGroupRule(
        f"{instance}-ingress-v4",
        security_group_id=sg.id,
        type="ingress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        cidr_ip="0.0.0.0/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )
    alicloud.ecs.SecurityGroupRule(
        f"{instance}-ingress-v6",
        security_group_id=sg.id,
        type="ingress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        ipv6_cidr_ip="::/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )

    # Add egress rules (allow all)
    alicloud.ecs.SecurityGroupRule(
        f"{instance}-egress-v4",
        security_group_id=sg.id,
        type="egress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        cidr_ip="0.0.0.0/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )
    alicloud.ecs.SecurityGroupRule(
        f"{instance}-egress-v6",
        security_group_id=sg.id,
        type="egress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        ipv6_cidr_ip="::/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )

    # Set user data if provided
    if user_data:
        instance_opts["user_data"] = user_data

    # Set disk size
    if disk_size:
        instance_opts["system_disk_size"] = disk_size

    # Set instance name and tags
    instance_opts["instance_name"] = instance
    instance_opts["tags"] = tags | {"Name": instance}

    # Create the ECS instance
    alicloud.ecs.Instance(
        instance,
        instance_type=instance,
        security_groups=[sg.id],
        vswitch_id=vswitch_id,
        opts=pulumi.ResourceOptions(provider=provider),
        **instance_opts,
    )


def resources_alicloud_multi(
    *,
    region: str,
    public_key: str,
    tags: dict,
    instance_opts: dict,
    sg_opts: dict,
    vpc_opts: dict,
    vswitch_opts: dict,
    image_name: str,
    availability_zone: str | None,
    shared_vpc_name_prefix: str,
    multi_vm: MultiVmStackSpec,
):
    instance_opts = copy.deepcopy(instance_opts)
    sg_opts = copy.deepcopy(sg_opts)
    vpc_opts = copy.deepcopy(vpc_opts)
    vswitch_opts = copy.deepcopy(vswitch_opts)

    provider = alicloud.Provider(resource_name=region, region=region)

    def resolve_image_id(instance_type: str) -> str:
        arch = data.server_cpu_architecture("alicloud", instance_type).lower().replace("i386", "x86_64")
        arch = "arm64" if "arm" in arch else "x86_64"
        images = alicloud.ecs.get_images(
            owners="system",
            name_regex=image_name,
            instance_type=instance_type,
            most_recent=True,
            opts=pulumi.InvokeOptions(provider=provider),
        )
        filtered = [img for img in images.images if img.architecture == arch]
        if not filtered:
            raise ValueError(f"No image found matching {image_name} for architecture {arch}")
        return filtered[0].id

    def pick_zone(instance_type: str, image_id: str) -> str:
        if availability_zone:
            return availability_zone
        instance_types = alicloud.ecs.get_instance_types(
            instance_type=instance_type,
            image_id=image_id,
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if instance_types.instance_types and instance_types.instance_types[0].availability_zones:
            return instance_types.instance_types[0].availability_zones[0]
        zones_data = alicloud.get_zones(
            available_resource_creation="VSwitch",
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if not zones_data.zones:
            raise ValueError(f"No zones available for VSwitch creation in region {region}")
        return zones_data.zones[0].id

    client_image = resolve_image_id(multi_vm.client_instance)
    db_image = resolve_image_id(multi_vm.db_instance)
    zone_id = pick_zone(multi_vm.client_instance, client_image)

    shared_vpc_id = lookup_shared_vpc_id(region, provider, shared_vpc_name_prefix)
    if shared_vpc_id:
        vpc_id = shared_vpc_id
    else:
        created_vpc = VpcNetwork(
            multi_vm.db_instance,
            vpc_name=f"sc-runner-{multi_vm.db_instance}",
            opts=pulumi.ResourceOptions(provider=provider),
            **vpc_opts,
        )
        vpc_id = created_vpc.id

    vswitch_id = None
    if shared_vpc_id and vpc_id == shared_vpc_id:
        vswitch_id = lookup_shared_vswitch_id(region, zone_id, vpc_id, provider, shared_vpc_name_prefix)
    if not vswitch_id:
        vswitch_input = copy.deepcopy(vswitch_opts) | {"vpc_id": vpc_id, "zone_id": zone_id}
        created_vswitch = VpcSwitch(
            multi_vm.db_instance,
            vswitch_name=f"sc-runner-{multi_vm.db_instance}",
            opts=pulumi.ResourceOptions(provider=provider),
            **vswitch_input,
        )
        vswitch_id = created_vswitch.id

    if public_key and "key_name" not in instance_opts:
        key_pair = alicloud.ecs.EcsKeyPair(
            multi_vm.db_instance,
            key_pair_name=multi_vm.db_instance,
            public_key=public_key,
            opts=pulumi.ResourceOptions(provider=provider),
        )
        key_name = key_pair.key_pair_name
    else:
        key_name = instance_opts.get("key_name")

    sg = alicloud.ecs.SecurityGroup(
        multi_vm.db_instance,
        security_group_name=multi_vm.db_instance,
        description="Security group created by sc-runner",
        vpc_id=vpc_id,
        opts=pulumi.ResourceOptions(provider=provider),
        **sg_opts,
    )
    alicloud.ecs.SecurityGroupRule(
        f"{multi_vm.db_instance}-ingress-v4",
        security_group_id=sg.id,
        type="ingress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        cidr_ip="0.0.0.0/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )
    alicloud.ecs.SecurityGroupRule(
        f"{multi_vm.db_instance}-egress-v4",
        security_group_id=sg.id,
        type="egress",
        ip_protocol="all",
        nic_type="intranet",
        policy="accept",
        port_range="-1/-1",
        priority=1,
        cidr_ip="0.0.0.0/0",
        opts=pulumi.ResourceOptions(provider=provider),
    )

    def vm_kwargs(instance_type: str, user_data_b64: pulumi.Input[str], disk_gib: int, image_id: str):
        kwargs = copy.deepcopy(instance_opts)
        kwargs["instance_name"] = instance_type
        kwargs["tags"] = tags | {"Name": instance_type}
        kwargs["user_data"] = user_data_b64
        kwargs["system_disk_size"] = disk_gib
        kwargs["image_id"] = image_id
        kwargs["availability_zone"] = zone_id
        if key_name:
            kwargs["key_name"] = key_name
        return kwargs

    client = alicloud.ecs.Instance(
        f"{multi_vm.client_instance}-client",
        instance_type=multi_vm.client_instance,
        security_groups=[sg.id],
        vswitch_id=vswitch_id,
        opts=pulumi.ResourceOptions(provider=provider),
        **vm_kwargs(multi_vm.client_instance, multi_vm.client_user_data_b64, multi_vm.client_disk_gib, client_image),
    )

    server_user_data_b64 = build_server_user_data_b64(multi_vm, client.private_ip)
    server = alicloud.ecs.Instance(
        multi_vm.db_instance,
        instance_type=multi_vm.db_instance,
        security_groups=[sg.id],
        vswitch_id=vswitch_id,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[client]),
        **(
            vm_kwargs(multi_vm.db_instance, server_user_data_b64, multi_vm.db_disk_gib, db_image)
            | {"availability_zone": client.availability_zone}
        ),
    )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=server.private_ip,
        client_private_ip=client.private_ip,
        db_public_ip=server.public_ip,
        client_public_ip=client.public_ip,
        region=region,
        zones=pulumi.Output.all(client.availability_zone, server.availability_zone).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )
