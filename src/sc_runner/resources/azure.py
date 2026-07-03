from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from .multi_vm import MultiVmStackSpec, build_server_user_data_b64, export_multi_vm_stack
from typing import Annotated
import click
import os
import pulumi
from pulumi_azure_native.compute import (
    HardwareProfileArgs,
    ImageReferenceArgs,
    LinuxConfigurationArgs,
    ManagedDiskParametersArgs,
    NetworkInterfaceReferenceArgs,
    NetworkProfileArgs,
    OSDiskArgs,
    OSProfileArgs,
    SshConfigurationArgs,
    SshPublicKeyArgs,
    StorageProfileArgs,
    VirtualMachine,
)
from pulumi_azure_native.network import (
    IPAllocationMethod,
    NetworkInterface,
    NetworkInterfaceIPConfigurationArgs,
    PublicIPAddress,
    PublicIPAddressArgs,
    Subnet,
    SubnetArgs,
    VirtualNetwork,
)
from pulumi_azure_native.resources import ResourceGroup


# defaults for JSON-based options
# key is the option variable name, value is a tuple of env var name and the default value
DEFAULTS = {
    "tags": ("TAGS", {"Created-by": "sc-runner"}),
    "vnet_opts": ("AZURE_VNET_OPTS", dict(address_space=dict(addressPrefixes=["10.0.0.0/16"]))),
    "subnet_opts": ("AZURE_SUBNET_OPTS", dict(address_prefix="10.0.1.0/24")),
    "publicip_opts": ("AZURE_PUBLICIP_OPTS", dict(delete_option="Delete", public_ip_allocation_method="Dynamic")),
}

def resources_azure(
        region: Annotated[str, DefaultOpt(["--region"], type=click.Choice(data.regions("azure")), help="Region"), StackName()] = os.environ.get("AZURE_REGION", "westeurope"),
        zone: Annotated[str, DefaultOpt(["--zone"], type=click.Choice(sorted(set(data.zones("azure")))), help="Availability zone"), StackName()] = os.environ.get("AZURE_ZONE", None),
        image_publisher: Annotated[str, DefaultOpt(["--image-publisher"], type=str, help="VM Image publisher")] = os.environ.get("AZURE_IMAGE_PUBLISHER", "Canonical"),
        # get the list of images in the mcr.microsoft.com/azure-cli Docker image (very slow):
        # az vm image list --publisher Canonical --all
        image_offer: Annotated[str, DefaultOpt(["--image-offer"], type=str, help="VM Image offer")] = os.environ.get("AZURE_IMAGE_OFFER", "ubuntu-24_04-lts"),
        image_sku: Annotated[str, DefaultOpt(["--image-sku"], type=str, help="VM Image SKU (auto-detected for ARM64 instances)")] = os.environ.get("AZURE_IMAGE_SKU", None),
        image_version: Annotated[str, DefaultOpt(["--image-version"], type=str, help="VM Image version")] = os.environ.get("AZURE_IMAGE_VERSION", "latest"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("azure")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "Standard_DS1_v2"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        tags: Annotated[str, DefaultOpt(["--tags"], type=JSON, default=defaults(DEFAULTS, "tags"), help="Tags for created resources")] = default(DEFAULTS, "tags"),
        vnet_opts: Annotated[str, DefaultOpt(["--vnet-opts"], type=JSON, default=defaults(DEFAULTS, "vnet_opts"), help="Pulumi azure-native.network.VirtualNetwork options")] = default(DEFAULTS, "vnet_opts"),
        subnet_opts: Annotated[str, DefaultOpt(["--subnet-opts"], type=JSON, default=defaults(DEFAULTS, "subnet_opts"), help="Pulumi azure-native.network.Subnet options")] = default(DEFAULTS, "subnet_opts"),
        publicip_opts: Annotated[str, DefaultOpt(["--publicip-opts"], type=JSON, default=defaults(DEFAULTS, "publicip_opts"), help="Pulumi azure-native.network.PublicIPAddress options")] = default(DEFAULTS, "publicip_opts"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
        multi_vm: MultiVmStackSpec | None = None,
):
    if multi_vm is not None:
        return resources_azure_multi(
            region=region,
            zone=zone,
            image_publisher=image_publisher,
            image_offer=image_offer,
            image_sku=image_sku,
            image_version=image_version,
            public_key=public_key,
            tags=tags,
            vnet_opts=vnet_opts,
            subnet_opts=subnet_opts,
            publicip_opts=publicip_opts,
            multi_vm=multi_vm,
        )
    # Auto-detect image SKU based on instance architecture if not provided
    if image_sku is None:
        arch = data.server_cpu_architecture("azure", instance).lower()
        if "arm" in arch:
            image_sku = "server-arm64"
        else:
            image_sku = "server"

    res_name = f"{region}{zone}{instance}"
    resource_group = ResourceGroup(
        instance,
        location=region,
        resource_group_name=res_name,
        tags=tags,
    )

    vnet = VirtualNetwork(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **vnet_opts,
    )

    subnet = Subnet(
        instance,
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        **subnet_opts,
    )

    public_ip = PublicIPAddress(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **publicip_opts,
    )

    network_interface = NetworkInterface(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        ip_configurations=[NetworkInterfaceIPConfigurationArgs(
            name=instance,
            subnet=SubnetArgs(
                id=subnet.id
            ),
            private_ip_allocation_method=IPAllocationMethod.DYNAMIC,
            public_ip_address=PublicIPAddressArgs(
                id=public_ip.id
            ))],
        tags=tags,
    )

    vmopts = dict(
        resource_group_name=resource_group.name,
        location=resource_group.location,
        network_profile=NetworkProfileArgs(
            network_interfaces=[NetworkInterfaceReferenceArgs(
                id=network_interface.id
            )]
        ),
        hardware_profile=HardwareProfileArgs(vm_size=instance),
        os_profile=OSProfileArgs(
            computer_name="sc-runner",
            admin_username="ubuntu",
            linux_configuration=LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=SshConfigurationArgs(
                    public_keys=[SshPublicKeyArgs(
                        key_data=public_key,
                        path="/home/ubuntu/.ssh/authorized_keys"
                    )
                    ]
                )
            ),
            custom_data=user_data,
        ),
            storage_profile=StorageProfileArgs(
                os_disk=OSDiskArgs(
                    create_option="FromImage",
                    managed_disk=ManagedDiskParametersArgs(
                        storage_account_type="Standard_LRS"
                    ),
                    caching="ReadWrite",
                    disk_size_gb=disk_size,
                ),
                image_reference=ImageReferenceArgs(
                    publisher=image_publisher,
                    offer=image_offer,
                    sku=image_sku,
                    version=image_version,
                ),
            ),
            tags=tags,
    )
    if zone is not None:
        vmopts["zones"] = [zone]
    vm = VirtualMachine(instance, **vmopts)


def resources_azure_multi(
    *,
    region: str,
    zone: str | None,
    image_publisher: str,
    image_offer: str,
    image_sku: str | None,
    image_version: str,
    public_key: str,
    tags: dict,
    vnet_opts: dict,
    subnet_opts: dict,
    publicip_opts: dict,
    multi_vm: MultiVmStackSpec,
):
    if image_sku is None:
        arch = data.server_cpu_architecture("azure", multi_vm.db_instance).lower()
        image_sku = "server-arm64" if "arm" in arch else "server"

    res_name = f"{region}{zone}{multi_vm.db_instance}"
    resource_group = ResourceGroup(
        multi_vm.db_instance,
        location=region,
        resource_group_name=res_name,
        tags=tags,
    )
    vnet = VirtualNetwork(
        multi_vm.db_instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **vnet_opts,
    )
    subnet = Subnet(
        multi_vm.db_instance,
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        **subnet_opts,
    )

    client_name = f"{multi_vm.client_instance}-client"
    server_name = multi_vm.db_instance

    client_public_ip = PublicIPAddress(
        client_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **publicip_opts,
    )
    client_nic = NetworkInterface(
        client_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        ip_configurations=[
            NetworkInterfaceIPConfigurationArgs(
                name=client_name,
                subnet=SubnetArgs(id=subnet.id),
                private_ip_allocation_method=IPAllocationMethod.DYNAMIC,
                public_ip_address=PublicIPAddressArgs(id=client_public_ip.id),
            )
        ],
        tags=tags,
    )
    client_vmopts = dict(
        resource_group_name=resource_group.name,
        location=resource_group.location,
        network_profile=NetworkProfileArgs(
            network_interfaces=[NetworkInterfaceReferenceArgs(id=client_nic.id)]
        ),
        hardware_profile=HardwareProfileArgs(vm_size=multi_vm.client_instance),
        os_profile=OSProfileArgs(
            computer_name="sc-client",
            admin_username="ubuntu",
            linux_configuration=LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=SshConfigurationArgs(
                    public_keys=[
                        SshPublicKeyArgs(
                            key_data=public_key,
                            path="/home/ubuntu/.ssh/authorized_keys",
                        )
                    ]
                ),
            ),
            custom_data=multi_vm.client_user_data_b64,
        ),
        storage_profile=StorageProfileArgs(
            os_disk=OSDiskArgs(
                create_option="FromImage",
                managed_disk=ManagedDiskParametersArgs(storage_account_type="Standard_LRS"),
                caching="ReadWrite",
                disk_size_gb=multi_vm.client_disk_gib,
            ),
            image_reference=ImageReferenceArgs(
                publisher=image_publisher,
                offer=image_offer,
                sku=image_sku,
                version=image_version,
            ),
        ),
        tags=tags,
    )
    if zone is not None:
        client_vmopts["zones"] = [zone]
    client_vm = VirtualMachine(client_name, **client_vmopts)

    client_private_ip = client_nic.ip_configurations.apply(
        lambda ipcs: ipcs[0].private_ip_address if ipcs and ipcs[0] else ""
    )
    server_user_data_b64 = build_server_user_data_b64(multi_vm, client_private_ip)

    server_public_ip = PublicIPAddress(
        server_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **publicip_opts,
    )
    server_nic = NetworkInterface(
        server_name,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        ip_configurations=[
            NetworkInterfaceIPConfigurationArgs(
                name=server_name,
                subnet=SubnetArgs(id=subnet.id),
                private_ip_allocation_method=IPAllocationMethod.DYNAMIC,
                public_ip_address=PublicIPAddressArgs(id=server_public_ip.id),
            )
        ],
        tags=tags,
    )
    server_vmopts = dict(
        resource_group_name=resource_group.name,
        location=resource_group.location,
        network_profile=NetworkProfileArgs(
            network_interfaces=[NetworkInterfaceReferenceArgs(id=server_nic.id)]
        ),
        hardware_profile=HardwareProfileArgs(vm_size=multi_vm.db_instance),
        os_profile=OSProfileArgs(
            computer_name="sc-server",
            admin_username="ubuntu",
            linux_configuration=LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=SshConfigurationArgs(
                    public_keys=[
                        SshPublicKeyArgs(
                            key_data=public_key,
                            path="/home/ubuntu/.ssh/authorized_keys",
                        )
                    ]
                ),
            ),
            custom_data=server_user_data_b64,
        ),
        storage_profile=StorageProfileArgs(
            os_disk=OSDiskArgs(
                create_option="FromImage",
                managed_disk=ManagedDiskParametersArgs(storage_account_type="Standard_LRS"),
                caching="ReadWrite",
                disk_size_gb=multi_vm.db_disk_gib,
            ),
            image_reference=ImageReferenceArgs(
                publisher=image_publisher,
                offer=image_offer,
                sku=image_sku,
                version=image_version,
            ),
        ),
        tags=tags,
    )
    if zone is not None:
        server_vmopts["zones"] = [zone]
    server_vm = VirtualMachine(server_name, opts=pulumi.ResourceOptions(depends_on=[client_vm]), **server_vmopts)

    db_private_ip = server_nic.ip_configurations.apply(
        lambda ipcs: ipcs[0].private_ip_address if ipcs and ipcs[0] else ""
    )
    zones = pulumi.Output.all(client_vm.zones, server_vm.zones).apply(
        lambda zs: [((zs[0] or [None])[0] if isinstance(zs[0], list) else zs[0]), ((zs[1] or [None])[0] if isinstance(zs[1], list) else zs[1])]
    )
    export_multi_vm_stack(
        spec=multi_vm,
        db_private_ip=db_private_ip,
        client_private_ip=client_private_ip,
        db_public_ip=server_public_ip.ip_address,
        client_public_ip=client_public_ip.ip_address,
        region=region,
        zones=zones,
        provisioned_disk_gib=multi_vm.db_disk_gib,
        client_disk_gib=multi_vm.client_disk_gib,
    )
