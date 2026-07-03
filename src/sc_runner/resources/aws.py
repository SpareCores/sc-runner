from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_aws as aws


V4_ALLOW_ALL = dict(ip_protocol="-1",
                    cidr_ipv4="0.0.0.0/0",
                    from_port=0,
                    to_port=0,
                    )
V6_ALLOW_ALL = dict(ip_protocol="-1",
                    cidr_ipv6="::/0",
                    from_port=0,
                    to_port=0,
                    )

# defaults for JSON-based options
# key is the option variable name, value is a tuple of env var name and the default value
DEFAULTS = {
    "tags": ("TAGS", {"Created-by": "sc-runner"}),
    "instance_opts": ("AWS_INSTANCE_OPTS", dict(associate_public_ip_address=True)),
    "vpc_opts": ("AWS_VPC_OPTS", dict()),
    "subnet_opts": ("AWS_SUBNET_OPTS", dict()),
    "sg_opts": ("AWS_SG_OPTS", dict()),
    "ingress_rules": ("AWS_INGRESS_RULES", [V4_ALLOW_ALL, V6_ALLOW_ALL]),
    "egress_rules": ("AWS_EGRESS_RULES", [V4_ALLOW_ALL, V6_ALLOW_ALL]),
}


def resources_aws(
        region: Annotated[str, DefaultOpt(["--region"], type=click.Choice(data.regions("aws")), help="Region"), StackName()] = os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        zone: Annotated[str, DefaultOpt(["--zone"], type=click.Choice(data.zones("aws")), help="Availability zone"), StackName()] = os.environ.get("AWS_ZONE", None),
        assume_role_arn: Annotated[str, DefaultOpt(["--assume-role-arn"], type=str, help="Role to be assumed")] = os.environ.get("AWS_ASSUME_ROLE_ARN", ""),
        ami_owner: Annotated[str, DefaultOpt(["--ami-owner"], type=str, help="AMI owner")] = os.environ.get("AWS_AMI_OWNER", "099720109477"),
        # to get the available image names:
        # aws ec2 describe-images --region us-east-1 --owners 099720109477 | jq '.Images[].Name'
        ami_name: Annotated[str, DefaultOpt(["--ami-name"], type=str, help="AWS name filter")] = os.environ.get("AWS_AMI_NAME", "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-*-server*"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("aws")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "t3.micro"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        tags: Annotated[str, DefaultOpt(["--tags"], type=JSON, default=defaults(DEFAULTS, "tags"), help="Tags for created resources")] = default(DEFAULTS, "tags"),
        instance_opts: Annotated[str, DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi aws.ec2.Instance options")] = default(DEFAULTS, "instance_opts"),
        vpc_opts: Annotated[str, DefaultOpt(["--vpc-opts"], type=JSON, default=defaults(DEFAULTS, "vpc_opts"), help="Pulumi aws.ec2.Vpc options")] = default(DEFAULTS, "vpc_opts"),
        subnet_opts: Annotated[str, DefaultOpt(["--subnet-opts"], type=JSON, default=defaults(DEFAULTS, "subnet_opts"), help="Pulumi aws.ec2.Subnet options")] = default(DEFAULTS, "subnet_opts"),
        sg_opts: Annotated[str, DefaultOpt(["--sg-opts"], type=JSON, default=defaults(DEFAULTS, "sg_opts"), help="Pulumi aws.ec2.SecurityGroup options")] = default(DEFAULTS, "sg_opts"),
        ingress_rules: Annotated[str, DefaultOpt(["--ingress-rules"], type=JSON, default=defaults(DEFAULTS, "ingress_rules"), help="List of Pulumi aws.vpc.SecurityGroupIngressRule options")] = default(DEFAULTS, "ingress_rules"),
        egress_rules: Annotated[str, DefaultOpt(["--egress-rules"], type=JSON, default=defaults(DEFAULTS, "egress_rules"), help="List of Pulumi aws.vpc.SecurityGroupEgressRule options")] = default(DEFAULTS, "egress_rules"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
        multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_aws_multi(
            region=region,
            zone=zone,
            assume_role_arn=assume_role_arn,
            ami_owner=ami_owner,
            ami_name=ami_name,
            public_key=public_key,
            tags=tags,
            instance_opts=instance_opts,
            vpc_opts=vpc_opts,
            subnet_opts=subnet_opts,
            sg_opts=sg_opts,
            ingress_rules=ingress_rules,
            egress_rules=egress_rules,
            multi_vm=multi_vm,
        )
    # as this function might be called multiple times, and we change the values below, we must make sure we work on copies
    instance_opts = copy.deepcopy(instance_opts)
    vpc_opts = copy.deepcopy(vpc_opts)
    subnet_opts = copy.deepcopy(subnet_opts)
    sg_opts = copy.deepcopy(sg_opts)
    prov_kwargs = {}
    if assume_role_arn:
        prov_kwargs["assume_role"] = aws.ProviderAssumeRoleArgs(role_arn=assume_role_arn)
    provider = aws.Provider(
        resource_name=region,
        region=region,
        skip_metadata_api_check=False,  # enable instance roles
        default_tags=aws.ProviderDefaultTagsArgs(tags=tags | {"Name": instance}),
        **prov_kwargs,
    )

    if public_key:
        pubkey = aws.ec2.KeyPair(
            instance,
            public_key=public_key,
            key_name=instance,
        )
        instance_opts["key_name"] = pubkey.id
    if user_data:
        instance_opts["user_data_base64"] = user_data
    if disk_size:
        instance_opts["root_block_device"] = aws.ec2.InstanceRootBlockDeviceArgs(volume_size=disk_size)

    if "ami" not in instance_opts:
        # some instances are marked as i386, but they aren't IA-32, replace them, so we can find AMIs
        arch = data.server_cpu_architecture("aws", instance).lower().replace("i386", "x86_64")
        ami = aws.ec2.get_ami(
            most_recent=True,  # in case of a filter is given as the name
            filters=[
                aws.ec2.GetAmiFilterArgs(name="architecture", values=[arch]),
                aws.ec2.GetAmiFilterArgs(name="name", values=[ami_name]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
            ],
            owners=[ami_owner],
            opts=pulumi.InvokeOptions(provider=provider),
        )
        instance_opts["ami"] = ami.id

    # If any of these are given, we assume that the required IDs are set everywhere and there's a working VPC/subnet/routing
    vpc_id = subnet_opts.get("vpc_id") or sg_opts.get("vpc_id")
    subnet_id = instance_opts.get("subnet_id")

    # If vpc_opts is given, we create a VPC/subnet/routing nevertheless
    if vpc_opts:
        vpc = aws.ec2.Vpc(instance, **vpc_opts)
        vpc_id = vpc.id

        subnet_opts["vpc_id"] = vpc.id
        subnet = aws.ec2.Subnet(instance, **subnet_opts)
        subnet_id = subnet.id

        igw = aws.ec2.InternetGateway(
            instance,
            vpc_id=vpc.id,
            opts=pulumi.ResourceOptions(provider=provider),
        )

        rt = aws.ec2.RouteTable(
            instance,
            vpc_id=vpc.id,
            routes=[
                aws.ec2.RouteTableRouteArgs(
                    cidr_block="0.0.0.0/0",
                    gateway_id=igw.id,
                ),
                aws.ec2.RouteTableRouteArgs(
                    ipv6_cidr_block="::/0",
                    gateway_id=igw.id,
                ),
            ],
            opts=pulumi.ResourceOptions(provider=provider),
        )
        aws.ec2.RouteTableAssociation(
            instance,
            subnet_id=subnet.id,
            route_table_id=rt.id,
            opts=pulumi.ResourceOptions(provider=provider),
        )

    if sg_opts or ingress_rules or egress_rules:
        sg_opts["vpc_id"] = vpc_id
        sg = aws.ec2.SecurityGroup(
            instance,
            opts=pulumi.ResourceOptions(provider=provider),
            **sg_opts,
        )
        instance_opts["vpc_security_group_ids"] = [sg.id]
        for i in range(len(ingress_rules)):
            aws.vpc.SecurityGroupIngressRule(
                f"{instance}-{i}",
                security_group_id=sg.id,
                opts=pulumi.ResourceOptions(provider=provider),
                **ingress_rules[i]
            )
        for i in range(len(egress_rules)):
            aws.vpc.SecurityGroupEgressRule(
                f"{instance}-{i}",
                security_group_id=sg.id,
                opts=pulumi.ResourceOptions(provider=provider),
                **egress_rules[i]
            )

    instance_opts["subnet_id"] = subnet_id
    aws.ec2.Instance(
        instance,
        instance_type=instance,
        opts=pulumi.ResourceOptions(provider=provider),
        **instance_opts,
    )


def resources_aws_multi(
    *,
    region: str,
    zone: str | None,
    assume_role_arn: str,
    ami_owner: str,
    ami_name: str,
    public_key: str,
    tags: dict,
    instance_opts: dict,
    vpc_opts: dict,
    subnet_opts: dict,
    sg_opts: dict,
    ingress_rules: list[dict],
    egress_rules: list[dict],
    multi_vm: MultiVmStackSpec,
):
    instance_opts = copy.deepcopy(instance_opts)
    vpc_opts = copy.deepcopy(vpc_opts)
    subnet_opts = copy.deepcopy(subnet_opts)
    sg_opts = copy.deepcopy(sg_opts)

    prov_kwargs = {}
    if assume_role_arn:
        prov_kwargs["assume_role"] = aws.ProviderAssumeRoleArgs(role_arn=assume_role_arn)
    provider = aws.Provider(
        resource_name=region,
        region=region,
        skip_metadata_api_check=False,
        default_tags=aws.ProviderDefaultTagsArgs(tags=tags | {"Name": multi_vm.db_instance}),
        **prov_kwargs,
    )

    common_opts = copy.deepcopy(instance_opts)
    if public_key and "key_name" not in common_opts:
        pubkey = aws.ec2.KeyPair(
            multi_vm.db_instance,
            public_key=public_key,
            key_name=multi_vm.db_instance,
            opts=pulumi.ResourceOptions(provider=provider),
        )
        common_opts["key_name"] = pubkey.id

    def resolve_ami(instance_type: str) -> str:
        arch = data.server_cpu_architecture("aws", instance_type).lower().replace("i386", "x86_64")
        ami = aws.ec2.get_ami(
            most_recent=True,
            filters=[
                aws.ec2.GetAmiFilterArgs(name="architecture", values=[arch]),
                aws.ec2.GetAmiFilterArgs(name="name", values=[ami_name]),
                aws.ec2.GetAmiFilterArgs(name="virtualization-type", values=["hvm"]),
            ],
            owners=[ami_owner],
            opts=pulumi.InvokeOptions(provider=provider),
        )
        return ami.id

    vpc = aws.ec2.Vpc(
        multi_vm.db_instance,
        opts=pulumi.ResourceOptions(provider=provider),
        **vpc_opts,
    )
    subnet_input = copy.deepcopy(subnet_opts) | {"vpc_id": vpc.id}
    if zone:
        subnet_input["availability_zone"] = zone
    subnet = aws.ec2.Subnet(
        multi_vm.db_instance,
        opts=pulumi.ResourceOptions(provider=provider),
        **subnet_input,
    )
    igw = aws.ec2.InternetGateway(
        multi_vm.db_instance,
        vpc_id=vpc.id,
        opts=pulumi.ResourceOptions(provider=provider),
    )
    rt = aws.ec2.RouteTable(
        multi_vm.db_instance,
        vpc_id=vpc.id,
        routes=[
            aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id),
            aws.ec2.RouteTableRouteArgs(ipv6_cidr_block="::/0", gateway_id=igw.id),
        ],
        opts=pulumi.ResourceOptions(provider=provider),
    )
    aws.ec2.RouteTableAssociation(
        multi_vm.db_instance,
        subnet_id=subnet.id,
        route_table_id=rt.id,
        opts=pulumi.ResourceOptions(provider=provider),
    )

    sg = aws.ec2.SecurityGroup(
        multi_vm.db_instance,
        vpc_id=vpc.id,
        opts=pulumi.ResourceOptions(provider=provider),
        **sg_opts,
    )
    for i, rule in enumerate(ingress_rules):
        aws.vpc.SecurityGroupIngressRule(
            f"{multi_vm.db_instance}-ingress-{i}",
            security_group_id=sg.id,
            opts=pulumi.ResourceOptions(provider=provider),
            **rule,
        )
    for i, rule in enumerate(egress_rules):
        aws.vpc.SecurityGroupEgressRule(
            f"{multi_vm.db_instance}-egress-{i}",
            security_group_id=sg.id,
            opts=pulumi.ResourceOptions(provider=provider),
            **rule,
        )

    client_opts = copy.deepcopy(common_opts)
    client_opts["ami"] = resolve_ami(multi_vm.client_instance)
    client_opts["user_data_base64"] = multi_vm.client_user_data_b64
    client_opts["subnet_id"] = subnet.id
    client_opts["associate_public_ip_address"] = True
    client_opts["vpc_security_group_ids"] = [sg.id]
    client_opts["root_block_device"] = aws.ec2.InstanceRootBlockDeviceArgs(volume_size=multi_vm.client_disk_gib)
    if zone:
        client_opts["availability_zone"] = zone

    client = aws.ec2.Instance(
        f"{multi_vm.client_instance}-client",
        instance_type=multi_vm.client_instance,
        opts=pulumi.ResourceOptions(provider=provider),
        **client_opts,
    )

    server_user_data_b64 = build_server_user_data_b64(multi_vm, client.private_ip)
    server_opts = copy.deepcopy(common_opts)
    server_opts["ami"] = resolve_ami(multi_vm.db_instance)
    server_opts["user_data_base64"] = server_user_data_b64
    server_opts["subnet_id"] = subnet.id
    server_opts["associate_public_ip_address"] = True
    server_opts["vpc_security_group_ids"] = [sg.id]
    server_opts["root_block_device"] = aws.ec2.InstanceRootBlockDeviceArgs(volume_size=multi_vm.db_disk_gib)
    server_opts["availability_zone"] = client.availability_zone

    server = aws.ec2.Instance(
        multi_vm.db_instance,
        instance_type=multi_vm.db_instance,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[client]),
        **server_opts,
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
