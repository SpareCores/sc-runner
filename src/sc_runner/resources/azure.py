from .. import DefaultOpt, JSON
from .. import data
from .base import StackName, default, defaults
from typing import Annotated
import click
import os
import pulumi_azure_native as azure_native


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
        image_sku: Annotated[str, DefaultOpt(["--image-sku"], type=str, help="VM Image SKU")] = os.environ.get("AZURE_IMAGE_SKU", "server"),
        image_version: Annotated[str, DefaultOpt(["--image-version"], type=str, help="VM Image version")] = os.environ.get("AZURE_IMAGE_VERSION", "latest"),
        instance: Annotated[str, DefaultOpt(["--instance"], type=click.Choice(data.servers("azure")), help="Instance type"), StackName()] = os.environ.get("INSTANCE_TYPE", "Standard_DS1_v2"),
        public_key: Annotated[str, DefaultOpt(["--public-key"], type=str, help="SSH public key")] = os.environ.get("SSH_PUBLIC_KEY", ""),
        tags: Annotated[str, DefaultOpt(["--tags"], type=JSON, default=defaults(DEFAULTS, "tags"), help="Tags for created resources")] = default(DEFAULTS, "tags"),
        vnet_opts: Annotated[str, DefaultOpt(["--vnet-opts"], type=JSON, default=defaults(DEFAULTS, "vnet_opts"), help="Pulumi azure-native.network.VirtualNetwork options")] = default(DEFAULTS, "vnet_opts"),
        subnet_opts: Annotated[str, DefaultOpt(["--subnet-opts"], type=JSON, default=defaults(DEFAULTS, "subnet_opts"), help="Pulumi azure-native.network.Subnet options")] = default(DEFAULTS, "subnet_opts"),
        publicip_opts: Annotated[str, DefaultOpt(["--publicip-opts"], type=JSON, default=defaults(DEFAULTS, "publicip_opts"), help="Pulumi azure-native.network.PublicIPAddress options")] = default(DEFAULTS, "publicip_opts"),
        user_data: Annotated[str | None, DefaultOpt(["--user-data"], type=str, help="Base64 encoded string with user_data script to run at boot")] = os.environ.get("USER_DATA", None),
        disk_size: Annotated[int, DefaultOpt(["--disk-size"], type=int, help="Boot disk size in GiBs")] = int(os.environ.get("DISK_SIZE", 30)),
):
    res_name = f"{region}{zone}{instance}"
    resource_group = azure_native.resources.ResourceGroup(
        instance,
        location=region,
        resource_group_name=res_name,
        tags=tags,
    )

    vnet = azure_native.network.VirtualNetwork(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **vnet_opts,
    )

    subnet = azure_native.network.Subnet(
        instance,
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        **subnet_opts,
    )

    public_ip = azure_native.network.PublicIPAddress(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        tags=tags,
        **publicip_opts,
    )

    network_interface = azure_native.network.NetworkInterface(
        instance,
        resource_group_name=resource_group.name,
        location=resource_group.location,
        ip_configurations=[azure_native.network.NetworkInterfaceIPConfigurationArgs(
            name=instance,
            subnet=azure_native.network.SubnetArgs(
                id=subnet.id
            ),
            private_ip_allocation_method=azure_native.network.IPAllocationMethod.DYNAMIC,
            public_ip_address=azure_native.network.PublicIPAddressArgs(
                id=public_ip.id
            ))],
        tags=tags,
    )

    vmopts = dict(
        resource_group_name=resource_group.name,
        location=resource_group.location,
        network_profile=azure_native.compute.NetworkProfileArgs(
            network_interfaces=[azure_native.compute.NetworkInterfaceReferenceArgs(
                id=network_interface.id
            )]
        ),
        hardware_profile=azure_native.compute.HardwareProfileArgs(vm_size=instance),
        os_profile=azure_native.compute.OSProfileArgs(
            computer_name="sc-runner",
            admin_username="ubuntu",
            linux_configuration=azure_native.compute.LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=azure_native.compute.SshConfigurationArgs(
                    public_keys=[azure_native.compute.SshPublicKeyArgs(
                        key_data=public_key,
                        path="/home/ubuntu/.ssh/authorized_keys"
                    )
                    ]
                )
            ),
            custom_data=user_data,
        ),
            storage_profile=azure_native.compute.StorageProfileArgs(
                os_disk=azure_native.compute.OSDiskArgs(
                    create_option="FromImage",
                    managed_disk=azure_native.compute.ManagedDiskParametersArgs(
                        storage_account_type="Standard_LRS"
                    ),
                    caching="ReadWrite",
                    disk_size_gb=disk_size,
                ),
                image_reference=azure_native.compute.ImageReferenceArgs(
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
    vm = azure_native.compute.VirtualMachine(instance, **vmopts)
