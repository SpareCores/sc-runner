import base64

from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
from typing import Annotated
import click
import copy
import os
import pulumi
import pulumi_gcp as gcp


DEFAULTS = {
    "instance_opts": ("GCP_INSTANCE_OPTS", dict(labels={"created-by": "sc-runner"})),
    "bootdisk_opts": ("GCP_BOOTDISK_OPTS", dict()),
    "bootdisk_init_opts": ("GCP_BOOTDISK_INIT_OPTS", dict(image="ubuntu-2404-lts-amd64")),
    "scheduling_opts": ("GCP_SCHEDULING_OPTS", dict()),
}

def resources_gcp(
        zone: Annotated[str, DefaultOpt(["--zone"], type=click.Choice(data.zones("gcp")), help="Availability zone"), StackName()] = os.environ.get("GCP_ZONE", "us-east1-d"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("gcp")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "e2-micro"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        instance_opts: Annotated[str, DefaultOpt(["--instance-opts"], type=JSON, default=defaults(DEFAULTS, "instance_opts"), help="Pulumi gcp.compute.Instance options")] = default(DEFAULTS, "instance_opts"),
        bootdisk_opts: Annotated[str, DefaultOpt(["--bootdisk-opts"], type=JSON, default=defaults(DEFAULTS, "bootdisk_opts"), help="Pulumi gcp.compute.InstanceBootDiskArgs options")] = default(DEFAULTS, "bootdisk_opts"),
        bootdisk_init_opts: Annotated[str, DefaultOpt(["--bootdisk-init-opts"], type=JSON, default=defaults(DEFAULTS, "bootdisk_init_opts"), help="Pulumi gcp.compute.InstanceBootDiskInitializeParamsArgs options")] = default(DEFAULTS, "bootdisk_init_opts"),
        scheduling_opts: Annotated[str, DefaultOpt(["--scheduling-opts"], type=JSON, default=defaults(DEFAULTS, "scheduling_opts"), help="Pulumi gcp.compute.InstanceSchedulingArgs options")] = default(DEFAULTS, "scheduling_opts"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
        multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_gcp_multi(
            zone=zone,
            public_key=public_key,
            instance_opts=instance_opts,
            bootdisk_opts=bootdisk_opts,
            bootdisk_init_opts=bootdisk_init_opts,
            scheduling_opts=scheduling_opts,
            multi_vm=multi_vm,
        )
    if "zone" in instance_opts:
        # as zone is part of the Pulumi stack name, it must be specified in the zone option and not in instance_opts
        raise ValueError("zone must be specified in the zone option")
    # we don't want to modify the default
    instance_opts = copy.deepcopy(instance_opts)
    if user_data:
        instance_opts["metadata_startup_script"] = base64.b64decode(user_data)
    if disk_size:
        bootdisk_init_opts["size"] = disk_size

    provider = gcp.Provider(
        resource_name=zone,
        zone=zone,
    )
    if public_key:
        if "metadata" in instance_opts:
            instance_opts["metadata"]["ssh-keys"] = f"ubuntu:{public_key}"
        else:
            instance_opts["metadata"] = {"ssh-keys": f"ubuntu:{public_key}"}
    instance_opts |= dict(
        machine_type=instance,
        zone=zone,
        boot_disk=gcp.compute.InstanceBootDiskArgs(
            initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(**bootdisk_init_opts),
            **bootdisk_opts,
        ),
        network_interfaces=[
            gcp.compute.InstanceNetworkInterfaceArgs(
                network="default",
                access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()]
            )
        ],
    )
    if scheduling_opts:
        instance_opts["scheduling"] = gcp.compute.InstanceSchedulingArgs(**scheduling_opts)
    gcp.compute.Instance(
        instance,
        **instance_opts,
        opts=pulumi.ResourceOptions(provider=provider),
    )


def resources_gcp_multi(
    *,
    zone: str,
    public_key: str,
    instance_opts: dict,
    bootdisk_opts: dict,
    bootdisk_init_opts: dict,
    scheduling_opts: dict,
    multi_vm: MultiVmStackSpec,
):
    provider = gcp.Provider(resource_name=zone, zone=zone)
    region = "-".join(zone.split("-")[:-1])

    network = gcp.compute.Network(
        multi_vm.db_instance,
        auto_create_subnetworks=False,
        opts=pulumi.ResourceOptions(provider=provider),
    )
    subnet = gcp.compute.Subnetwork(
        multi_vm.db_instance,
        network=network.id,
        region=region,
        ip_cidr_range="10.0.1.0/24",
        opts=pulumi.ResourceOptions(provider=provider),
    )
    gcp.compute.Firewall(
        f"{multi_vm.db_instance}-allow-internal",
        network=network.id,
        source_ranges=["10.0.0.0/8"],
        allows=[
            gcp.compute.FirewallAllowArgs(protocol="tcp"),
            gcp.compute.FirewallAllowArgs(protocol="udp"),
            gcp.compute.FirewallAllowArgs(protocol="icmp"),
        ],
        opts=pulumi.ResourceOptions(provider=provider),
    )
    gcp.compute.Firewall(
        f"{multi_vm.db_instance}-allow-ssh",
        network=network.id,
        source_ranges=["0.0.0.0/0"],
        allows=[gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["22"])],
        opts=pulumi.ResourceOptions(provider=provider),
    )

    common_instance_opts = copy.deepcopy(instance_opts)
    if public_key:
        metadata = copy.deepcopy(common_instance_opts.get("metadata", {}))
        metadata["ssh-keys"] = f"ubuntu:{public_key}"
        common_instance_opts["metadata"] = metadata
    if scheduling_opts:
        common_instance_opts["scheduling"] = gcp.compute.InstanceSchedulingArgs(**scheduling_opts)

    def vm_opts(instance_type: str, user_data_b64: pulumi.Input[str], disk_gib: int):
        opts = copy.deepcopy(common_instance_opts)
        init = copy.deepcopy(bootdisk_init_opts)
        init["size"] = disk_gib
        opts |= dict(
            machine_type=instance_type,
            zone=zone,
            metadata_startup_script=pulumi.Output.from_input(user_data_b64).apply(lambda b: base64.b64decode(b).decode("utf-8")),
            boot_disk=gcp.compute.InstanceBootDiskArgs(
                initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(**init),
                **bootdisk_opts,
            ),
            network_interfaces=[
                gcp.compute.InstanceNetworkInterfaceArgs(
                    subnetwork=subnet.id,
                    access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()],
                )
            ],
        )
        return opts

    client = gcp.compute.Instance(
        f"{multi_vm.client_instance}-client",
        **vm_opts(multi_vm.client_instance, multi_vm.client_user_data_b64, multi_vm.client_disk_gib),
        opts=pulumi.ResourceOptions(provider=provider),
    )
    client_private_ip = client.network_interfaces.apply(lambda nis: nis[0].network_ip if nis else "")

    server_user_data_b64 = build_server_user_data_b64(multi_vm, client_private_ip)
    server = gcp.compute.Instance(
        multi_vm.db_instance,
        **(
            vm_opts(multi_vm.db_instance, server_user_data_b64, multi_vm.db_disk_gib)
            | {"zone": client.zone}
        ),
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[client]),
    )

    def private_ip(instance):
        return instance.network_interfaces.apply(lambda nis: nis[0].network_ip if nis else "")

    def public_ip(instance):
        return instance.network_interfaces.apply(
            lambda nis: nis[0].access_configs[0].nat_ip if nis and nis[0].access_configs else ""
        )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=private_ip(server),
        client_private_ip=client_private_ip,
        db_public_ip=public_ip(server),
        client_public_ip=public_ip(client),
        region=region,
        zones=pulumi.Output.all(client.zone, server.zone).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )