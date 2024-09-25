from .aws import resources_aws
from .azure import resources_azure
from .base import *
from .gcp import resources_gcp
from .hcloud import resources_hcloud
import inspect
import sys

# method name prefix for initializing vendor-specific resources
PREFIX = "resources_"


supported_vendors = {
    name[len(PREFIX):] for name, _ in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
    if name.startswith(PREFIX)
}
