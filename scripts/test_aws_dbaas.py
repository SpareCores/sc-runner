"""Smoke-test AWS RDS DBaaS stack (private Postgres + companion client).

Creates a small stack, prints outputs, then destroys it unless --keep is set.

Example (inside sc-runner docker image with local source installed):

  AWS_PROFILE=sc \\
  SC_DATA_DB_PATH=/data/sc-data-all.db SC_DATA_NO_UPDATE=1 \\
  PULUMI_BACKEND_URL=file:///data/backend PULUMI_CONFIG_PASSPHRASE= \\
  python /scripts/test_aws_dbaas.py
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
REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
DB_CLASS = os.environ.get("RDS_INSTANCE_CLASS", "db.t3.micro")
CLIENT_INSTANCE = os.environ.get("CLIENT_INSTANCE", "t3.micro")
ENGINE_VERSION = os.environ.get("RDS_ENGINE_VERSION", "18")
STORAGE_GIB = int(os.environ.get("RDS_STORAGE_GIB", "64"))
SLUG = os.environ.get("DBAAS_SLUG", "awstest-pg18")


def _build_spec() -> DbaasStackSpec:
    client_ud = base64.b64encode(
        b"#!/bin/bash\nset -euo pipefail\necho aws-dbaas-client-ok > /tmp/sc-aws-dbaas-test\n"
    ).decode()
    md = ManagedDbSpec(
        engine="postgres",
        engine_version=ENGINE_VERSION,
        native_id=DB_CLASS,
        sku_name=DB_CLASS,
        ha_mode="standalone",
        storage_gib=STORAGE_GIB,
        storage_type="gp3",
        storage_edition="gp3",
        storage_iops=3000,
        storage_throughput_mb_s=125,
        admin_login="scadmin",
        database_name="bench",
    )
    return DbaasStackSpec(
        managed_db=md,
        client_instance=CLIENT_INSTANCE,
        client_disk_gib=30,
        client_user_data_b64=client_ud,
        instance_key_slug=SLUG,
        extra_exports={"topology": "dbaas", "test": "aws_dbaas_smoke"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Do not destroy the stack after a successful create",
    )
    parser.add_argument(
        "--destroy-only",
        action="store_true",
        help="Only destroy an existing smoke-test stack",
    )
    args = parser.parse_args()

    stack_name = os.environ.get(
        "PULUMI_STACK_NAME",
        f"aws.{REGION}.None.{CLIENT_INSTANCE}.{SLUG}",
    )
    resource_opts = {
        "region": REGION,
        "instance": CLIENT_INSTANCE,
        "public_key": PUBKEY,
        "dbaas_slug": SLUG,
        "dbaas": _build_spec(),
    }
    pulumi_opts = {"stack_name": stack_name}

    if args.destroy_only:
        print(f"Destroying stack {stack_name}", flush=True)
        runner.destroy_stack("aws", pulumi_opts, resource_opts)
        print("Destroy finished", flush=True)
        return 0

    print(
        f"Creating AWS DBaaS stack {stack_name}: RDS {DB_CLASS} pg{ENGINE_VERSION} "
        f"+ client {CLIENT_INSTANCE} in {REGION}",
        flush=True,
    )
    try:
        runner.create("aws", pulumi_opts, resource_opts)
    except Exception:
        traceback.print_exc()
        print("Create failed; attempting destroy to clean up", flush=True)
        try:
            runner.destroy_stack("aws", pulumi_opts, resource_opts)
        except Exception:
            traceback.print_exc()
            print("Cleanup destroy also failed", flush=True)
        return 1

    stack = runner.get_stack("aws", pulumi_opts, resource_opts)
    outputs = stack.outputs()
    print("Stack outputs:", flush=True)
    required = ("db_fqdn", "db_port", "client_public_ip", "topology", "native_id")
    missing = []
    for key in sorted(outputs):
        val = outputs[key].value
        # Avoid printing secrets in full
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
            runner.destroy_stack("aws", pulumi_opts, resource_opts)
        return 2

    print("Create OK", flush=True)
    if args.keep:
        print(f"Keeping stack {stack_name} (--keep)", flush=True)
        return 0

    print(f"Destroying stack {stack_name}", flush=True)
    runner.destroy_stack("aws", pulumi_opts, resource_opts)
    print("Destroy OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
