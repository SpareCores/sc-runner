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
        images = alicloud.ecs.get_images(
            owners="system",
            name_regex=image_name,
            architecture=arch,
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if not images.images:
            raise ValueError(f"No image found matching {image_name} for architecture {arch}")
        instance_opts["image_id"] = images.images[0].id

    # Get VPC if not provided
    vpc_id = sg_opts.get("vpc_id") or instance_opts.get("vpc_id")
    vswitch_id = instance_opts.get("vswitch_id")
    created_vpc = None

    if not vpc_id:
        # First try to get the default VPC
        vpc_data = alicloud.vpc.get_networks(
            is_default=True,
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if vpc_data.vpcs:
            vpc_id = vpc_data.vpcs[0].vpc_id
        else:
            # No default VPC, try to get any VPC
            vpc_data = alicloud.vpc.get_networks(
                opts=pulumi.InvokeOptions(provider=provider),
            )
            if vpc_data.vpcs:
                vpc_id = vpc_data.vpcs[0].vpc_id

    # If still no VPC, create one
    if not vpc_id:
        created_vpc = alicloud.vpc.Network(
            instance,
            vpc_name=f"sc-runner-{instance}",
            opts=pulumi.ResourceOptions(provider=provider),
            **vpc_opts,
        )
        vpc_id = created_vpc.id

    # Get a vswitch if not provided
    if not vswitch_id:
        # Only search for existing vswitches if we didn't create the VPC
        if created_vpc is None:
            vswitch_data = alicloud.vpc.get_switches(
                vpc_id=vpc_id,
                opts=pulumi.InvokeOptions(provider=provider),
            )
            if vswitch_data.vswitches:
                vswitch_id = vswitch_data.vswitches[0].vswitch_id

    # If still no vswitch, create one
    if not vswitch_id:
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
