"""Smoke-test OVHcloud managed Postgres DBaaS stack.

Creates a small stack, prints outputs, then destroys it unless --keep is set.

Example:

  SC_DATA_DB_PATH=/data/sc-data-all.db SC_DATA_NO_UPDATE=1 \\
  PULUMI_BACKEND_URL=file:///data/backend PULUMI_CONFIG_PASSPHRASE= \\
    python /app/scripts/test_ovh_dbaas.py
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import traceback

from sc_runner import runner
from sc_runner.resources.managed_db import DbaasStackSpec, ManagedDbSpec

PUBKEY = os.environ.get(
    "SSH_PUBLIC_KEY",
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEPMwX6HY8inovVAqUrAKvqY0zabNoWfmN/7UlNsBvZ4 info@sparecores.com",
)
REGION = os.environ.get("OVH_REGION", "GRA")
DB_NATIVE = os.environ.get("OVH_DB_NATIVE", "postgresql-essential-db1-4")
DB_PLAN = os.environ.get("OVH_DB_PLAN", "essential")
DB_FLAVOR = os.environ.get("OVH_DB_FLAVOR", "db1-4")
CLIENT_INSTANCE = os.environ.get("CLIENT_INSTANCE", "d2-2")
CLIENT_REGION = os.environ.get("OVH_CLIENT_REGION")  # default: sc-data companion_region
ENGINE_VERSION = os.environ.get("OVH_ENGINE_VERSION", "18")
STORAGE_GIB = int(os.environ.get("OVH_STORAGE_GIB", "80"))
SLUG = os.environ.get("DBAAS_SLUG", "ovhtest-pg18")
PROJECT_ID = os.environ.get("OVH_CLOUD_PROJECT_SERVICE") or os.environ.get(
    "OVH_PROJECT_ID"
)


def _build_spec() -> DbaasStackSpec:
    client_ud = base64.b64encode(
        b"#!/bin/bash\nset -euo pipefail\necho ovh-dbaas-client-ok > /tmp/sc-ovh-dbaas-test\n"
    ).decode()
    md = ManagedDbSpec(
        engine="postgres",
        engine_version=ENGINE_VERSION,
        native_id=DB_NATIVE,
        sku_name=DB_FLAVOR,
        sku_tier=DB_PLAN,
        ha_mode="standalone",
        storage_gib=STORAGE_GIB,
        admin_login="avnadmin",
        database_name="bench",
    )
    return DbaasStackSpec(
        managed_db=md,
        client_instance=CLIENT_INSTANCE,
        client_disk_gib=30,
        client_user_data_b64=client_ud,
        instance_key_slug=SLUG,
        extra_exports={"topology": "dbaas", "test": "ovh_dbaas_smoke"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--destroy-only", action="store_true")
    args = parser.parse_args()

    if not PROJECT_ID:
        print("OVH_CLOUD_PROJECT_SERVICE / OVH_PROJECT_ID required", flush=True)
        return 3

    stack_name = os.environ.get(
        "PULUMI_STACK_NAME",
        f"ovh.{REGION}.{CLIENT_INSTANCE}.{SLUG}",
    )
    resource_opts = {
        "project_id": PROJECT_ID,
        "region": REGION,
        "instance": CLIENT_INSTANCE,
        "public_key": PUBKEY,
        "dbaas_slug": SLUG,
        "dbaas": _build_spec(),
    }
    if CLIENT_REGION:
        resource_opts["client_region"] = CLIENT_REGION
    pulumi_opts = {"stack_name": stack_name}

    if args.destroy_only:
        print(f"Destroying stack {stack_name}", flush=True)
        runner.destroy_stack("ovh", pulumi_opts, resource_opts)
        print("Destroy finished", flush=True)
        return 0

    print(
        f"Creating OVH DBaaS stack {stack_name}: {DB_PLAN}/{DB_FLAVOR} "
        f"pg{ENGINE_VERSION} + client {CLIENT_INSTANCE} "
        f"(db={REGION}, client={CLIENT_REGION or 'auto'})",
        flush=True,
    )
    try:
        runner.create("ovh", pulumi_opts, resource_opts)
    except Exception:
        traceback.print_exc()
        print("Create failed; attempting destroy to clean up", flush=True)
        try:
            runner.destroy_stack("ovh", pulumi_opts, resource_opts)
        except Exception:
            traceback.print_exc()
            print("Cleanup destroy also failed", flush=True)
        return 1

    stack = runner.get_stack("ovh", pulumi_opts, resource_opts)
    outputs = stack.outputs()
    print("Stack outputs:", flush=True)
    required = ("db_fqdn", "db_port", "client_public_ip", "topology", "native_id")
    missing = []
    for key in sorted(outputs):
        val = outputs[key].value
        if "password" in key.lower():
            print(f"  {key}: <secret set={bool(val)}>", flush=True)
        else:
            print(f"  {key}: {val}", flush=True)
    for key in required:
        if key not in outputs or not outputs[key].value:
            missing.append(key)
    if missing:
        print(f"FAIL: missing/empty outputs: {missing}", flush=True)
        if not args.keep:
            runner.destroy_stack("ovh", pulumi_opts, resource_opts)
        return 2

    print("Create OK", flush=True)
    if args.keep:
        print(f"Keeping stack {stack_name} (--keep)", flush=True)
        return 0

    print(f"Destroying stack {stack_name}", flush=True)
    runner.destroy_stack("ovh", pulumi_opts, resource_opts)
    print("Destroy OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
