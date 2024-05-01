import inspect
import sys
from .aws import resources_aws
from .base import *

# method name prefix for initializing vendor-specific resources
PREFIX = "resources_"


supported_vendors = {
    name[len(PREFIX):] for name, _ in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
    if name.startswith(PREFIX)
}
