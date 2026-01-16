from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_alicloud as alicloud


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
):
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
            opts=pulumi.InvokeOptions(provider=provider),
        )
        # Filter images by architecture in Python since the provider doesn't support arm64 filter
        filtered_images = [img for img in images.images if img.architecture == arch]
        if not filtered_images:
            raise ValueError(f"No image found matching {image_name} for architecture {arch}")
        instance_opts["image_id"] = filtered_images[0].id

    # Always create a dedicated VPC and vswitch for this instance to avoid conflicts
    # when the function is called multiple times with the same arguments
    vpc_id = sg_opts.get("vpc_id") or instance_opts.get("vpc_id")
    vswitch_id = instance_opts.get("vswitch_id")

    # Only create VPC if not explicitly provided
    if not vpc_id:
        created_vpc = alicloud.vpc.Network(
            instance,
            vpc_name=f"sc-runner-{instance}",
            opts=pulumi.ResourceOptions(provider=provider),
            **vpc_opts,
        )
        vpc_id = created_vpc.id

    # Only create vswitch if not explicitly provided
    if not vswitch_id:
        if availability_zone:
            # Use the specified availability zone
            zone_id = availability_zone
        else:
            # Get available zones for VSwitch creation
            zones_data = alicloud.get_zones(
                available_resource_creation="VSwitch",
                opts=pulumi.InvokeOptions(provider=provider),
            )
            if not zones_data.zones:
                raise ValueError(f"No zones available for VSwitch creation in region {region}")
            zone_id = zones_data.zones[0].id
        
        vswitch_opts["vpc_id"] = vpc_id
        vswitch_opts["zone_id"] = zone_id

        created_vswitch = alicloud.vpc.Switch(
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
