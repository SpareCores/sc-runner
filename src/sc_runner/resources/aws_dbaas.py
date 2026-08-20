"""AWS RDS for PostgreSQL + companion benchmark VM in one Pulumi stack."""

from __future__ import annotations

import re
import secrets
import string

import pulumi
import pulumi_aws as aws

from .. import data
from .azure_dbaas import export_dbaas_stack
from .managed_db import DbaasStackSpec
from .multi_vm import VmSpec, build_user_data_b64

# Reuse AWS provider retry / instance create timeout helpers.
from .aws_config import aws_provider, instance_resource_opts

NETWORK_MODE = "private_vpc"
DEFAULT_VPC_CIDR = "10.0.0.0/16"
CLIENT_SUBNET_CIDR = "10.0.1.0/24"
DB_SUBNET_CIDRS = ("10.0.2.0/24", "10.0.3.0/24")


def _random_password(length: int = 24) -> str:
    # RDS master passwords reject '/', '@', '"', and spaces.
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _rds_identifier(slug: str) -> str:
    """RDS DB identifier: 1–63 chars, lowercase letters/digits/hyphens."""
    raw = re.sub(r"[^a-z0-9-]", "", slug.lower())
    name = f"sc-{raw}".strip("-")
    if not name or not name[0].isalpha():
        name = f"sc{name}"
    return name[:63].rstrip("-")


def _postgres_engine_version(engine_version: str) -> str:
    """Pass major (or major.minor) through; RDS resolves the concrete patch."""
    return str(engine_version).strip()


def resources_aws_dbaas(
    *,
    region: str,
    zone: str | None,
    assume_role_arn: str,
    ami_owner: str,
    ami_name: str,
    public_key: str,
    tags: dict,
    instance_opts: dict,
    dbaas: DbaasStackSpec,
) -> None:
    """Provision private RDS Postgres + public client EC2 in a dedicated VPC."""
    md = dbaas.managed_db
    slug = dbaas.instance_key_slug or "dbaas"
    instance_opts = dict(instance_opts)

    provider = aws_provider(
        resource_name=region,
        region=region,
        tags=tags | {"Name": slug},
        assume_role_arn=assume_role_arn,
    )
    opts = pulumi.ResourceOptions(provider=provider)

    azs = aws.get_availability_zones(
        state="available",
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if len(azs.names) < 2:
        raise RuntimeError(f"AWS region {region} needs ≥2 AZs for an RDS subnet group")
    client_az = zone if zone and zone in azs.names else azs.names[0]
    other_az = next(a for a in azs.names if a != client_az)
    db_azs = [client_az, other_az]

    vpc = aws.ec2.Vpc(
        slug,
        cidr_block=DEFAULT_VPC_CIDR,
        enable_dns_hostnames=True,
        enable_dns_support=True,
        opts=opts,
    )
    igw = aws.ec2.InternetGateway(slug, vpc_id=vpc.id, opts=opts)
    public_rt = aws.ec2.RouteTable(
        f"{slug}-public",
        vpc_id=vpc.id,
        routes=[
            aws.ec2.RouteTableRouteArgs(cidr_block="0.0.0.0/0", gateway_id=igw.id),
        ],
        opts=opts,
    )

    client_subnet = aws.ec2.Subnet(
        f"{slug}-client",
        vpc_id=vpc.id,
        cidr_block=CLIENT_SUBNET_CIDR,
        availability_zone=client_az,
        map_public_ip_on_launch=True,
        opts=opts,
    )
    aws.ec2.RouteTableAssociation(
        f"{slug}-client-rta",
        subnet_id=client_subnet.id,
        route_table_id=public_rt.id,
        opts=opts,
    )

    db_subnets = []
    for i, (cidr, az) in enumerate(zip(DB_SUBNET_CIDRS, db_azs)):
        subnet = aws.ec2.Subnet(
            f"{slug}-db-{i}",
            vpc_id=vpc.id,
            cidr_block=cidr,
            availability_zone=az,
            map_public_ip_on_launch=False,
            opts=opts,
        )
        db_subnets.append(subnet)

    db_subnet_group = aws.rds.SubnetGroup(
        slug,
        name=_rds_identifier(f"{slug}-subnets"),
        subnet_ids=[s.id for s in db_subnets],
        opts=opts,
    )

    client_sg = aws.ec2.SecurityGroup(
        f"{slug}-client",
        vpc_id=vpc.id,
        description="DBaaS benchmark client",
        opts=opts,
    )
    aws.vpc.SecurityGroupIngressRule(
        f"{slug}-client-ssh",
        security_group_id=client_sg.id,
        ip_protocol="tcp",
        from_port=22,
        to_port=22,
        cidr_ipv4="0.0.0.0/0",
        opts=opts,
    )
    aws.vpc.SecurityGroupEgressRule(
        f"{slug}-client-egress",
        security_group_id=client_sg.id,
        ip_protocol="-1",
        cidr_ipv4="0.0.0.0/0",
        opts=opts,
    )

    db_sg = aws.ec2.SecurityGroup(
        f"{slug}-db",
        vpc_id=vpc.id,
        description="DBaaS RDS Postgres",
        opts=opts,
    )
    aws.vpc.SecurityGroupIngressRule(
        f"{slug}-db-pg",
        security_group_id=db_sg.id,
        ip_protocol="tcp",
        from_port=5432,
        to_port=5432,
        referenced_security_group_id=client_sg.id,
        opts=opts,
    )
    aws.vpc.SecurityGroupEgressRule(
        f"{slug}-db-egress",
        security_group_id=db_sg.id,
        ip_protocol="-1",
        cidr_ipv4="0.0.0.0/0",
        opts=opts,
    )

    admin_password = md.admin_password or _random_password()
    storage_type = (md.storage_type or "gp3").lower()
    rds_kwargs: dict = dict(
        identifier=_rds_identifier(slug),
        engine="postgres",
        engine_version=_postgres_engine_version(md.engine_version),
        instance_class=md.sku_name or md.native_id,
        allocated_storage=md.storage_gib,
        storage_type=storage_type,
        db_subnet_group_name=db_subnet_group.name,
        vpc_security_group_ids=[db_sg.id],
        username=md.admin_login or "scadmin",
        password=admin_password,
        port=5432,
        publicly_accessible=False,
        multi_az=False,
        backup_retention_period=0,
        skip_final_snapshot=True,
        deletion_protection=False,
        auto_minor_version_upgrade=True,
        apply_immediately=True,
        storage_encrypted=True,
        # Private VPC clients connect without TLS (matches GCP ALLOW_UNENCRYPTED).
        # Parameter groups could force SSL; leave defaults.
    )
    if storage_type == "gp3":
        # RDS Postgres rejects custom IOPS/throughput below 400 GiB allocated storage.
        if md.storage_gib >= 400:
            if md.storage_iops is not None:
                rds_kwargs["iops"] = int(md.storage_iops)
            if md.storage_throughput_mb_s is not None:
                rds_kwargs["storage_throughput"] = int(md.storage_throughput_mb_s)
    elif storage_type in ("io1", "io2") and md.storage_iops is not None:
        rds_kwargs["iops"] = int(md.storage_iops)

    # Single-AZ: pin to the client AZ when possible so cross-AZ latency is avoided.
    if client_az:
        rds_kwargs["availability_zone"] = client_az

    pg = aws.rds.Instance(
        _rds_identifier(slug),
        opts=pulumi.ResourceOptions(provider=provider, depends_on=db_subnets),
        **rds_kwargs,
    )

    default_bindings = {
        "SC_DB_HOST": ("db", "fqdn"),
        "SC_DB_PASSWORD": ("db", "password"),
    }
    if dbaas.client_user_data_b64 and not (
        dbaas.client_user_data_bindings or dbaas.client_user_data_template
    ):
        client_bindings: dict[str, tuple[str, str]] = {}
    else:
        client_bindings = dbaas.client_user_data_bindings or default_bindings

    client_vm_spec = VmSpec(
        role="client",
        instance=dbaas.client_instance,
        disk_gib=dbaas.client_disk_gib,
        disk_type=dbaas.client_disk_type,
        user_data_b64=dbaas.client_user_data_b64,
        user_data_template=dbaas.client_user_data_template,
        user_data_static=dbaas.client_user_data_static,
        user_data_bindings=client_bindings,
    )
    db_sources = {
        ("db", "fqdn"): pg.address,
        ("db", "password"): admin_password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    arch = data.server_cpu_architecture("aws", dbaas.client_instance).lower().replace(
        "i386", "x86_64"
    )
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

    client_opts = dict(instance_opts)
    if public_key and "key_name" not in client_opts:
        pubkey = aws.ec2.KeyPair(
            f"{slug}-client",
            public_key=public_key,
            key_name=f"{slug}-client",
            opts=opts,
        )
        client_opts["key_name"] = pubkey.id
    client_opts["ami"] = ami.id
    client_opts["user_data_base64"] = client_user_data
    client_opts["subnet_id"] = client_subnet.id
    client_opts["associate_public_ip_address"] = True
    client_opts["vpc_security_group_ids"] = [client_sg.id]
    client_opts["availability_zone"] = client_az
    client_opts["root_block_device"] = aws.ec2.InstanceRootBlockDeviceArgs(
        volume_size=dbaas.client_disk_gib,
        volume_type=dbaas.client_disk_type or "gp3",
    )

    client = aws.ec2.Instance(
        f"{dbaas.client_instance}-client",
        instance_type=dbaas.client_instance,
        opts=instance_resource_opts(provider, depends_on=[pg]),
        **client_opts,
    )

    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=[client_az],
        db_fqdn=pg.address,
        db_port=5432,
        db_bootstrap_login=md.admin_login or "scadmin",
        db_bootstrap_database="postgres",
        db_admin_login=md.admin_login or "scadmin",
        db_admin_password=pulumi.Output.secret(admin_password),
        client_private_ip=client.private_ip,
        client_public_ip=client.public_ip,
        storage_gib=md.storage_gib,
        network_mode=NETWORK_MODE,
    )
