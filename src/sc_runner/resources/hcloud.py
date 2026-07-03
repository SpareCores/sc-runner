from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
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
        multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_hcloud_multi(
            region=region,
            public_key=public_key,
            instance_opts=instance_opts,
            multi_vm=multi_vm,
        )

    # we don't want to modify the default
    instance_opts = copy.deepcopy(instance_opts)

    if public_key and "ssh_keys" not in instance_opts:
        ssh_key = hcloud.SshKey(
            instance,
            name=instance,
            public_key=public_key
        )
        instance_opts["ssh_keys"] = [ssh_key.id]

    instance_opts.pop("datacenter", None)

    hcloud.Server(
        instance,
        name=instance,
        image="ubuntu-24.04",
        server_type=instance,
        location=data.hcloud_location(region),
        user_data=user_data,
        **instance_opts,
    )


def resources_hcloud_multi(
    *,
    region: str,
    public_key: str,
    instance_opts: dict,
    multi_vm: MultiVmStackSpec,
):
    instance_opts = copy.deepcopy(instance_opts)
    instance_opts.pop("datacenter", None)

    if public_key and "ssh_keys" not in instance_opts:
        ssh_key = hcloud.SshKey(
            multi_vm.db_instance,
            name=multi_vm.db_instance,
            public_key=public_key,
        )
        ssh_keys = [ssh_key.id]
    else:
        ssh_keys = instance_opts.get("ssh_keys")

    network = hcloud.Network(
        multi_vm.db_instance,
        name=f"{multi_vm.db_instance}-private",
        ip_range="10.0.0.0/16",
    )
    subnet = hcloud.NetworkSubnet(
        multi_vm.db_instance,
        network_id=network.id.apply(lambda nid: int(nid)),
        type="cloud",
        network_zone="eu-central",
        ip_range="10.0.1.0/24",
    )

    client = hcloud.Server(
        f"{multi_vm.client_instance}-client",
        name=f"{multi_vm.client_instance}-client",
        image="ubuntu-24.04",
        server_type=multi_vm.client_instance,
        location=data.hcloud_location(region),
        user_data=multi_vm.client_user_data_b64,
        ssh_keys=ssh_keys,
        **instance_opts,
    )
    client_network = hcloud.ServerNetwork(
        f"{multi_vm.client_instance}-client-net",
        server_id=client.id.apply(lambda sid: int(sid)),
        subnet_id=subnet.id,
    )

    server_user_data_b64 = build_server_user_data_b64(multi_vm, client_network.ip)
    server = hcloud.Server(
        multi_vm.db_instance,
        name=multi_vm.db_instance,
        image="ubuntu-24.04",
        server_type=multi_vm.db_instance,
        location=data.hcloud_location(region),
        user_data=server_user_data_b64,
        ssh_keys=ssh_keys,
        opts=pulumi.ResourceOptions(depends_on=[client]),
        **instance_opts,
    )
    server_network = hcloud.ServerNetwork(
        f"{multi_vm.db_instance}-net",
        server_id=server.id.apply(lambda sid: int(sid)),
        subnet_id=subnet.id,
    )

    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=server_network.ip,
        client_private_ip=client_network.ip,
        db_public_ip=server.ipv4_address,
        client_public_ip=client.ipv4_address,
        region=region,
        zones=pulumi.Output.all(client.datacenter, server.datacenter).apply(lambda zs: [zs[0], zs[1]]),
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )