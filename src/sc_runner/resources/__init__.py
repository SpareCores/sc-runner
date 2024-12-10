import inspect
import sys

from .aws import resources_aws as resources_aws
from .azure import resources_azure as resources_azure
from .base import *
from .gcp import resources_gcp as resources_gcp
from .hcloud import resources_hcloud as resources_hcloud
from .upcloud import resources_upcloud as resources_upcloud

# method name prefix for initializing vendor-specific resources
PREFIX = "resources_"


supported_vendors = {
    name[len(PREFIX) :]
    for name, _ in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
    if name.startswith(PREFIX)
}
