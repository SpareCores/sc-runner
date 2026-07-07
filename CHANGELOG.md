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
