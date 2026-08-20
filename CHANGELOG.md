# v0.0.73 (2026-08-20)

- AWS: bound provider API retries (`max_retries=3`, `retry_mode=standard` by default)
  and EC2 create timeout (`5m`) so `InsufficientInstanceCapacity` fails in minutes
  instead of ~50m (SDK default 25 attempts). Override with `AWS_MAX_RETRIES` /
  `AWS_INSTANCE_CREATE_TIMEOUT` / `AWS_RETRY_MODE`.

# v0.0.72 (2026-08-20)

- Add AWS RDS DBaaS stack: `resources_aws_dbaas()` provisions private Postgres +
  companion client EC2 (dedicated VPC, DB subnet group across 2 AZs, gp3 IOPS/throughput)
- `resources_aws()` dispatches `dbaas=` stacks via `dbaas_slug` (same pattern as Azure/GCP)
- `ManagedDbSpec`: optional `storage_iops` / `storage_throughput_mb_s` for AWS gp3
- `data.database_region_prices()` for cheapest-first DBaaS region ordering
- AWS DBaaS: only set gp3 IOPS/throughput when `storage_gib >= 400` (RDS Postgres limit);
  unique Pulumi name for client route-table association

# v0.0.71 (2026-08-20)

- AWS multi-VM: use shallow copies of instance opts after `key_name` is set to a
  Pulumi Output; `copy.deepcopy(Output)` raises
  `__getstate__ can only be called during serialization` and aborts stack create

# v0.0.70 (2026-08-20)

- AWS multi-VM: set default VPC/subnet CIDR blocks (`10.0.0.0/16` / `10.0.1.0/24`) when
  `AWS_VPC_OPTS` / `AWS_SUBNET_OPTS` omit them; aws provider v7 rejects CreateVpc without
  `cidrBlock`

# v0.0.69 (2026-08-02)

- GCP DBaaS: force-load `pulumi_gcp.compute` / `.servicenetworking` / `.sql` once at
  module-import time instead of relying on their first (lazy) attribute access.
  `pulumi_gcp` binds those subpackages via `importlib.util.LazyLoader`, which is not
  thread-safe; sc-inspector's `start-dbaas` runs several DBaaS stacks concurrently in
  a `ThreadPoolExecutor` in one process, so two threads racing to first-touch e.g.
  `gcp.sql` could observe a partially-executed module and fail with
  `AttributeError: module 'pulumi_gcp.sql' has no attribute 'DatabaseInstance'. Did
  you mean: 'database_instance'?` (confirmed live in a real run — other, concurrently
  running stacks succeeded in the same instant, confirming the race rather than a
  permanent/version issue)

# v0.0.68 (2026-08-01)

- GCP: force ARM64 boot image + `architecture=ARM64` for Tau T2A / Axion C4A / N4A
  (fixes `boot disk architecture (X86_64) is not compatible with machine type architecture (ARM64)`)
- GCP: `apply_gcp_boot_disk_defaults()` now respects an explicit `architecture` already
  set by the caller (e.g. sc-inspector's per-instance catalog lookup) instead of always
  overwriting it from a hardcoded ARM-series list, which was silently discarding correct
  caller-supplied values. It now also swaps the `-amd64`/`-arm64` suffix on whatever
  `image` is passed in (rather than hardcoding both per-arch image names), so
  `bootdisk_init_opts`'s default only needs to name the x86_64 Ubuntu image once
- GCP: `gcp_boot_architecture()` now looks up `Server.cpu_architecture` in the sc-crawler
  catalog (same pattern as `resources/azure.py` and `resources/alicloud.py`) instead of a
  hardcoded machine-series list, now that sc-crawler reads GCP's real `MachineType.architecture`
  API field (confirmed live: correctly `ARM64` for C4A/N4A today) instead of its own
  hardcoded `t2a`-only check

# v0.0.67 (2026-08-01)

- GCP: auto-select `hyperdisk-balanced` boot disks for Hyperdisk-only machine series
  (C4/C4A/C4D/C4N, N4/N4A/N4D, G4, A3/A4/A4X, X4, M4N, H4D) so create no longer fails with
  `pd-ssd disk type cannot be used by …`
- GCP DBaaS: use Cloud SQL `HYPERDISK_BALANCED` for `db-c4a-*` / `db-n4-*` tiers (PD_SSD is invalid)
- GCP DBaaS: only set `data_cache_config` for `ENTERPRISE_PLUS` so n1/Enterprise tiers are not
  forced into Enterprise Plus (fixes `Invalid Tier (db-n1-*) for (ENTERPRISE_PLUS) Edition`)

# v0.0.66 (2026-07-29)

- GCP DBaaS: set Cloud SQL `settings.edition` to `ENTERPRISE_PLUS` for perf/memory-optimized and C4A tiers
- GCP DBaaS: explicitly disable Enterprise Plus data cache (`data_cache_enabled=False`) so Postgres DBaaS scores stay comparable to multi-VM (API default is on)
- Release workflow: pass bare semver as `image_tag` (matches GHCR `sc-runner:X.Y.Z`), not the raw git tag

# v0.0.65 (2026-07-16)

- Azure single-VM: expose `--disk-type` / `--disk-iops` / `--disk-throughput` (env `DISK_TYPE`, `DISK_IOPS`, `DISK_THROUGHPUT`) so the OS disk can use the same managed-disk tiers as multi-VM (`Premium_LRS`, `PremiumV2_LRS`, …); default remains `Standard_LRS`

# v0.0.64 (2026-07-10)

- Fix `render_user_data()` placeholder substitution when replacement values reference other keys (repeat until stable so DBaaS bootstrap passwords are not left as unresolved `{SC_DB_PASSWORD}` literals)

# v0.0.63 (2026-07-10)

- GCP DBaaS: set `deletion_policy="ABANDON"` on the private-service-access `servicenetworking.Connection` so stack destroy no longer fails with "producer services (Cloud SQL) are still using this connection" (Cloud SQL releases the PSA peering asynchronously; the peering is cleaned up with the VPC network)
- GCP DBaaS: set `update_on_creation_fail=True` on the PSA connection to reconcile a leftover connection instead of failing when a slug-scoped network is recreated

# v0.0.62 (2026-07-09)

- Fix Azure import: use `get_client_config_output` from `pulumi_azure_native.authorization` (fixes `ModuleNotFoundError: No module named 'pulumi_azure_native.core'` on `inspector.py start`)

# v0.0.61 (2026-07-09)

- DBaaS: provision empty managed Postgres instances only; database and workload users are bootstrapped by sc-inspector (Azure and GCP)
- Azure multi-VM: support `PremiumV2_LRS` / `UltraSSD_LRS` DB host OS disks with provisioned IOPS and throughput when requested; export `db_disk_type`, `db_disk_iops`, and `db_disk_throughput` from multi-VM stacks
- Remove bundled unit tests under `tests/`

# v0.0.60 (2026-07-08)

- Fix broken 0.0.59 release: include missing `gcp_project.py` module (fixes `ModuleNotFoundError` on import)

# v0.0.59 (2026-07-08)

- GCP: resolve lowercase `project_id` for Pulumi provider and Cloud SQL (reject numeric project numbers / display names; fall back to `GOOGLE_CREDENTIALS.project_id`)

# v0.0.58 (2026-07-08)

- Ship `gcp_dbaas.py`: Cloud SQL Postgres + PSA private-IP networking and companion client VM stack (fixes broken `gcp_dbaas` import in 0.0.57)

# v0.0.57 (2026-07-08)

- Add GCP DBaaS dispatch in `resources_gcp()` (`dbaas_slug` stack name segment)

# v0.0.56 (2026-07-08)

- Azure DBaaS: export `db_admin_password` as a Pulumi secret so stack updates do not print credentials in CI logs

# v0.0.55 (2026-07-08)

- Azure DBaaS: clamp PremiumV2 IOPS/throughput to Azure-valid ranges (minimum 3000 IOPS / 125 MB/s; size-based maximum)

# v0.0.54 (2026-07-08)

- Azure DBaaS: fix private DNS zone and VNet link `location` to `global` so Postgres private-link stacks deploy reliably
- Azure DBaaS: support `PremiumV2_LRS` / `UltraSSD_LRS` Flexible Server storage with explicit IOPS and throughput; keep `Premium_LRS` on tier-based `StorageArgs`
- `ManagedDbSpec`: split `storage_edition` (catalog label) from `storage_type` (ARM storage SKU); export `storage_edition` from the stack
- Azure DBaaS: skip default DB user-data bindings when only raw `client_user_data_b64` is supplied

# v0.0.53 (2026-07-07)

- Add Azure DBaaS stack provisioning: `ManagedDbSpec` / `DbaasStackSpec` plus `resources_azure_dbaas()` provisions Azure Flexible Server for Postgres and a companion benchmark VM in one Pulumi stack
- Azure DBaaS uses a private VNet with delegated Postgres subnet, private DNS zone, and no public firewall rules; stack exports `db_fqdn`, credentials, and client IPs for sc-inspector user-data
- Azure `resources_azure()` dispatches `dbaas=` stacks via `dbaas_slug` in the stack name for per-cache-tier provisioning

# v0.0.52 (2026-07-06)

- `VmSpec`: add generic optional per-VM storage knobs (`disk_type`, `disk_iops`, `disk_throughput`) honored by the AWS, Azure, and GCP multi-VM stacks; when unset the provider default is used. `MultiVmStackSpec.two_vm` exposes `primary_disk_*` / `client_disk_type` so callers can pick a storage tier without any benchmark-specific defaults living in sc-runner
- Drop unused/redundant multi-VM code: the `db_*`/`client_*` stack-output aliases (identical to the `{role}_*` exports), the unused generic `export_stack` wrapper, and the unused `MultiVmStackSpec.primary_instance` / `server_user_data_replacements` accessors

# v0.0.51 (2026-07-03)

- Add generic `multi_vm` stack support: role-based `VmSpec`, templated user-data bindings, and shared stack exports for multi-VM workloads
- All eight vendors (AWS, Azure, GCP, Alicloud, HCloud, OVH, UpCloud, Vultr) can provision paired client + primary VMs via `MultiVmStackSpec`

# v0.0.50 (2026-06-30)

- Add `server_region_prices`, `server_zone_prices`, and `sort_by_price` for cheapest-first region/zone selection from sc-data
- Remove Vultr `filter_regions` / `cleanup_regions`; regional fallback lives in sc-inspector

# v0.0.48 (2026-06-15)

- Alicloud: add `cleanup_regions()` to union catalog, zone, and plan-pricing regions for inspector cleanup
- `destroy_stack`: tolerate refresh/destroy failures when cloud resources are already gone (Vultr 404/invalid instance-id; Alicloud missing ECS instances and security groups)
- `destroy_stack`: prune ghost custom resources from Pulumi state via `export_stack`/`import_stack`, retry destroy, and force-remove the stack when needed

# v0.0.46 (2026-06-15)

- `destroy_stack`: continue when Pulumi refresh reports missing Vultr instances (404), so stale stacks can still be destroyed
- Vultr: add `cleanup_regions()` to union catalog regions with deployable-plan regions during inspector cleanup

# v0.0.45 (2026-06-12)

- Vultr: use `BareMetalServer` for `vbm-*` plans; remap block-only VX1 plans to storage-suffixed siblings via sc-data; filter regions using sc-data for the deployable plan

# v0.0.44 (2026-06-11)

- Require `pulumi-aws>=6.83.4` for `aws.vpc.SecurityGroupIngressRule` / `SecurityGroupEgressRule` support on Python 3.12

# v0.0.43 (2026-06-05)

- Add Vultr support (`sc-runner create vultr`, `ediri-vultr` dependency)
- Fix Hetzner Cloud deprecated `datacenter` field; use `location` with datacenter-to-location mapping from sc-data
- Publish multi-arch (`amd64` + `arm64`) `ghcr.io/sparecores/sc-runner` Docker image
- Upgrade GitHub Actions for image and release workflows

# v0.0.42 (2026-04-07)

- Alibaba Cloud: create dedicated VpcNetwork and VpcSwitch per instance to avoid VPC conflicts

# v0.0.41 (2026-04-07)

- Alibaba Cloud: retry instance creation without `system_disk_category` when the plan does not support `cloud_auto`

# v0.0.40 (2026-02-17)

- Revert default instance images back to Ubuntu 24.04 due to GPU driver issues on newer releases

# v0.0.39 (2026-01-16)

- Alibaba Cloud: add `--availability-zone` for zone-scoped instance creation

# v0.0.38 (2026-01-15)

- Version bump

# v0.0.37 (2026-01-14)

- Alibaba Cloud: default `system_disk_category` to `cloud_auto` and filter images by CPU architecture

# v0.0.36 (2026-01-14)

- Add support for Alibaba Cloud

# v0.0.35 (2025-12-30)

- Update OVHcloud instance image to Ubuntu 25.04 due to poor memory performance on Ubuntu 24.04

# v0.0.34 (2025-12-15)

- Decrease OVHcloud instance creation timeout from 1 hour to 10 minutes

# v0.0.33 (2025-12-08)

- Fix passing OVHcloud project ID env var directly when using runner.create() instead of the CLI

# v0.0.32 (2025-12-07)

- Add support for OVHcloud

# v0.0.31 (2025-12-06)

- Fix default None with click 8.3.0+

# v0.0.30 (2024-12-16)

- Add support for UpCloud

# v0.0.29 (2024-09-25)

- Add support for Hetzner Cloud

# Previous Versions

As listed at <https://github.com/SpareCores/sc-runner/releases>.
