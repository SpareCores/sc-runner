import inspect
import sys

from .aws import resources_aws
from .azure import resources_azure
from .base import *
from .gcp import resources_gcp
from .hcloud import resources_hcloud
from .ovh import resources_ovh
from .upcloud import resources_upcloud

# method name prefix for initializing vendor-specific resources
PREFIX = "resources_"


supported_vendors = {
    name[len(PREFIX) :]
    for name, _ in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
    if name.startswith(PREFIX)
}


__all__ = [
    "resources_aws",
    "resources_azure",
    "resources_gcp",
    "resources_hcloud",
    "resources_ovh",
    "resources_upcloud",
    "supported_vendors",
]
