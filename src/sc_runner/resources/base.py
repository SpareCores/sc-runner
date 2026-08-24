import copy
import os
import json

from .. import DefaultOpt


class StackName:
    """Class to signal that an argument's value should be included in the auto-generated Pulumi stack name."""
    pass


def defaults(defaults, opt_name):
    """Return default value from `defaults` for the `opt_name` as a string."""
    # do a copy, so it's not possible to modify the defaults
    envvar, def_val = copy.deepcopy(defaults[opt_name])
    return os.environ.get(envvar, json.dumps(def_val))


def default(defaults, opt_name):
    """Return default value from `defaults` for the `opt_name` as a Python object(dict)."""
    # do a copy, so it's not possible to modify the defaults
    envvar, def_val = copy.deepcopy(defaults[opt_name])
    return json.loads(os.environ.get(envvar, "null")) or def_val


def spot_from_env() -> bool:
    """Default for --spot/--no-spot from the SPOT env var."""
    return os.environ.get("SPOT", "").strip().lower() in ("1", "true", "yes", "on")


def spot_opt() -> DefaultOpt:
    """Per-command Click option (fresh instance; Click mutates Option objects)."""
    return DefaultOpt(
        ["--spot/--no-spot"],
        help="Request Spot/preemptible capacity when the vendor supports it (env: SPOT)",
    )


# Vendors where --spot maps to a real preemptible/Spot API.
SPOT_SUPPORTED_VENDORS = frozenset({"aws", "gcp", "azure", "alicloud"})


def ensure_spot_supported(vendor: str, spot: bool) -> None:
    if spot and vendor not in SPOT_SUPPORTED_VENDORS:
        raise ValueError(
            f"--spot is not supported for {vendor}; "
            f"supported vendors: {', '.join(sorted(SPOT_SUPPORTED_VENDORS))}"
        )

