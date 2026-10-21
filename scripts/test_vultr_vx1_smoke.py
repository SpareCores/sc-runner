#!/usr/bin/env python3
"""Smoke: Vultr diskless VX1 resolve_plan + cheap create/destroy.

1. Remap catalog diskless SKUs (incl. INACTIVE-sibling cases) and confirm the
   remapped plan id still appears on Vultr GET /v2/plans.
2. Create then destroy a small diskless VX1 (``vx1-g-2c-8g`` -> ``-120s``).

Example:

  SSH_PUBLIC_KEY="$(cat ~/.ssh/id_ed25519.pub)" \\
  SC_DATA_DB_PATH=/home/bra/tmp/sc-data-all.db SC_DATA_NO_UPDATE=1 \\
  PULUMI_BACKEND_URL=file:///tmp/vultr-vx1-backend PULUMI_WORK_DIR=/tmp/vultr-vx1-workdir \\
  VULTR_API_KEY=... python scripts/test_vultr_vx1_smoke.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_ssh import require_ssh_public_key  # noqa: E402

from sc_runner import runner
from sc_runner.resources.vultr import resolve_plan

REGION = os.environ.get("VULTR_REGION", "ewr")
SMOKE_INSTANCE = os.environ.get("VULTR_SMOKE_INSTANCE", "vx1-g-2c-8g")
DISK_SIZE = int(os.environ.get("DISK_SIZE", "30"))
CHECK_PLANS = (
    "vx1-g-96c-384g",
    "vx1-g-192c-768g",
    "vx1-m-96c-768gb",
    SMOKE_INSTANCE,
)


def _vultr_plan_ids() -> set[str]:
    key = os.environ.get("VULTR_API_KEY", "").strip()
    if not key:
        raise RuntimeError("VULTR_API_KEY is required")
    req = urllib.request.Request(
        "https://api.vultr.com/v2/plans?per_page=500",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    return {p["id"] for p in body.get("plans") or []}


def _check_resolve() -> dict[str, str]:
    api_plans = _vultr_plan_ids()
    print(f"vultr API plans listed: {len(api_plans)}", flush=True)
    mapped: dict[str, str] = {}
    for plan in CHECK_PLANS:
        remapped = resolve_plan(plan, DISK_SIZE)
        mapped[plan] = remapped
        in_api = remapped in api_plans
        print(f"  resolve_plan {plan} -> {remapped} (in_api={in_api})", flush=True)
        if not in_api:
            raise RuntimeError(
                f"remapped plan {remapped!r} missing from Vultr /v2/plans; "
                "INACTIVE sibling may be retired (need Instance.block_devices)"
            )
        if plan != SMOKE_INSTANCE and remapped == plan:
            raise RuntimeError(f"expected remap for diskless {plan}")
    return mapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--destroy-only", action="store_true")
    parser.add_argument("--resolve-only", action="store_true")
    args = parser.parse_args()

    try:
        mapped = _check_resolve()
    except Exception:
        traceback.print_exc()
        return 1
    if args.resolve_only:
        print("RESOLVE_OK", flush=True)
        return 0

    pubkey = require_ssh_public_key()
    smoke_plan = mapped[SMOKE_INSTANCE]
    stack_name = os.environ.get(
        "PULUMI_STACK_NAME",
        f"vultr.{REGION}.{SMOKE_INSTANCE}",
    )
    resource_opts = {
        "region": REGION,
        "instance": SMOKE_INSTANCE,
        "public_key": pubkey,
        "disk_size": DISK_SIZE,
    }
    pulumi_opts = {"stack_name": stack_name}

    if args.destroy_only:
        print(f"Destroying stack {stack_name}", flush=True)
        runner.destroy("vultr", pulumi_opts, resource_opts)
        print("DESTROY_OK", flush=True)
        return 0

    try:
        print(
            f"Creating {SMOKE_INSTANCE} as plan={smoke_plan} in {REGION}",
            flush=True,
        )
        outs = runner.create("vultr", pulumi_opts, resource_opts)
        print("CREATE_OK", flush=True)
        print(json.dumps({k: str(v) for k, v in (outs or {}).items()}, indent=2), flush=True)
    except Exception:
        traceback.print_exc()
        print("CREATE_FAIL; attempting destroy", flush=True)
        try:
            runner.destroy_stack("vultr", pulumi_opts, resource_opts)
        except Exception:
            traceback.print_exc()
        return 1

    if args.keep:
        print("KEEP set; skipping destroy", flush=True)
        return 0

    try:
        runner.destroy("vultr", pulumi_opts, resource_opts)
        print("DESTROY_OK", flush=True)
    except Exception:
        traceback.print_exc()
        try:
            runner.destroy_stack("vultr", pulumi_opts, resource_opts)
            print("DESTROY_STACK_OK", flush=True)
        except Exception:
            traceback.print_exc()
            return 1
    print("SMOKE_EXIT=0", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
