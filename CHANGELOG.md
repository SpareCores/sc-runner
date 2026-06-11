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
