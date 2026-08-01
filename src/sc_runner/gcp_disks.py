"""GCP disk-type helpers for machine series that reject Persistent Disk.

Fourth-generation general-purpose families (C4/C4A/C4D/N4/…) and several
accelerator / memory / network series support Hyperdisk only. Using the
Compute Engine / Cloud SQL default of ``pd-ssd`` / ``PD_SSD`` fails with
``pd-ssd disk type cannot be used by …`` or
``PD_SSD disk type is not supported for tier …``.

Sources (Google Cloud docs):
  * https://cloud.google.com/compute/docs/general-purpose-machines
  * https://cloud.google.com/compute/docs/accelerator-optimized-machines
  * https://cloud.google.com/compute/docs/memory-optimized-machines
  * https://cloud.google.com/sql/docs/postgres/storage-options-overview
  * https://cloud.google.com/sql/docs/postgres/machine-series-overview
"""

from __future__ import annotations

# GCE machine series that do not support pd-ssd / pd-balanced / pd-standard.
# Boot and attached disks must be Hyperdisk (typically hyperdisk-balanced).
# Z3 still allows PD; C3/C3D allow PD — do not include those.
_HYPERDISK_ONLY_SERIES = frozenset(
    {
        # General-purpose 4th gen
        "c4",
        "c4a",
        "c4d",
        "c4n",
        "n4",
        "n4a",
        "n4d",
        # Accelerator-optimized
        "a3",
        "a4",
        "a4x",
        "g4",
        # Memory-optimized
        "x4",
        "m4n",
        # Network-optimized (Titanium / Hyperdisk-only families)
        "h4d",
    }
)

_GCE_PD_TYPES = frozenset({"pd-ssd", "pd-balanced", "pd-standard", "pd-extreme"})
_CLOUD_SQL_PD_TYPES = frozenset({"PD_SSD", "PD_HDD"})

GCE_HYPERDISK_BALANCED = "hyperdisk-balanced"
CLOUD_SQL_HYPERDISK_BALANCED = "HYPERDISK_BALANCED"


def gcp_machine_series(machine_type: str) -> str:
    """Return the series prefix of a GCE machine type (``c4-highmem-48`` → ``c4``)."""
    return (machine_type or "").split("-", 1)[0].lower()


def gcp_requires_hyperdisk(machine_type: str) -> bool:
    """True when ``machine_type`` cannot attach Persistent Disk volumes."""
    return gcp_machine_series(machine_type) in _HYPERDISK_ONLY_SERIES


def gcp_boot_disk_type(machine_type: str, requested: str | None = None) -> str | None:
    """Resolve GCE boot-disk ``type`` for ``machine_type``.

    Returns ``hyperdisk-balanced`` when the series is Hyperdisk-only and
    ``requested`` is unset or a Persistent Disk type. Otherwise returns
    ``requested`` unchanged (``None`` leaves the provider/API default).
    """
    if gcp_requires_hyperdisk(machine_type):
        if not requested or requested.lower() in _GCE_PD_TYPES:
            return GCE_HYPERDISK_BALANCED
        return requested
    return requested


def cloud_sql_tier_series(tier: str) -> str:
    """Series key for a Cloud SQL tier (``db-c4a-highmem-4`` → ``c4a``)."""
    raw = (tier or "").lower()
    if raw.startswith("db-"):
        raw = raw[3:]
    # db-perf-optimized-N-8 / db-memory-optimized-N-8 / db-n1-standard-4 / db-c4a-highmem-4
    if raw.startswith(("perf-optimized", "memory-optimized", "custom")):
        return "n2"  # Enterprise Plus N2-shaped tiers use PD_SSD
    return raw.split("-", 1)[0]


def cloud_sql_requires_hyperdisk(tier: str) -> bool:
    """True when Cloud SQL ``tier`` requires ``HYPERDISK_BALANCED`` storage."""
    # Cloud SQL Hyperdisk series today: C4A (Enterprise Plus) and N4 (Enterprise).
    # https://cloud.google.com/sql/docs/postgres/storage-options-overview
    return cloud_sql_tier_series(tier) in {"c4a", "n4"}


def cloud_sql_disk_type(tier: str, requested: str | None = None) -> str:
    """Resolve Cloud SQL ``settings.disk_type`` for ``tier``."""
    if cloud_sql_requires_hyperdisk(tier):
        if not requested or requested.upper() in _CLOUD_SQL_PD_TYPES:
            return CLOUD_SQL_HYPERDISK_BALANCED
        return requested
    return requested or "PD_SSD"
