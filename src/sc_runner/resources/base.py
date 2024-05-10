import os
import json


class StackName:
    """Class to signal that an argument's value should be included in the auto-generated Pulumi stack name."""
    pass


def defaults(defaults, opt_name):
    """Return default value from `defaults` for the `opt_name` as a string."""
    envvar, def_val = defaults[opt_name]
    return os.environ.get(envvar, json.dumps(def_val))


def default(defaults, opt_name):
    """Return default value from `defaults` for the `opt_name` as a Python object(dict)."""
    envvar, def_val = defaults[opt_name]
    return json.loads(os.environ.get(envvar, "null")) or def_val

