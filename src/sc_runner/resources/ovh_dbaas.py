"""OVHcloud Managed Database (Postgres) + companion benchmark VM in one Pulumi stack.

Private network lives in a compute region from sc-data (DBaaS catalog codes like
GRA are not valid for NetworkPrivate). DB nodes keep the catalog region but
attach to that compute region's OpenStack network/subnet so the client stays on
the internal path.
"""

from __future__ import annotations

import re
import secrets
import string

import pulumi
import pulumi_ovh as ovh
from pulumi import CustomTimeouts, ResourceOptions

from .. import data
from .azure_dbaas import export_dbaas_stack
from .managed_db import DbaasStackSpec
from .multi_vm import VmSpec, build_user_data_b64
from .ovh import find_resource_id, instance_ipv4

NETWORK_MODE = "private_vpc"
PRIVATE_CIDR = "10.1.0.0/24"


def ovh_compute_region(db_region: str) -> str:
    """Resolve a compute region for an OVH DBaaS catalog region via sc-data."""
    return data.companion_region("ovh", db_region)


def _random_token(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _sanitize_name(slug: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9-]", "-", slug).strip("-")
    return (raw or "sc-dbaas")[:63]


def resources_ovh_dbaas(
    *,
    project_id: str,
    region: str,
    image_name: str,
    instance_opts: dict,
    dbaas: DbaasStackSpec,
    client_region: str | None = None,
) -> None:
    """Provision private-network OVH managed Postgres + public+private client VM.

    ``region`` is the DBaaS node region (catalog, e.g. GRA). The companion VM and
    private network use ``client_region`` (default: companion compute from
    sc-data, e.g. GRA11).
    """
    md = dbaas.managed_db
    slug = _sanitize_name(dbaas.instance_key_slug or "dbaas")
    instance_opts = dict(instance_opts)
    vm_region = client_region or ovh_compute_region(region)

    flavors = ovh.cloudproject.get_flavors(service_name=project_id)
    client_flavor_id = find_resource_id(
        flavors.flavors, dbaas.client_instance, "instance type", vm_region
    )
    images = ovh.cloudproject.get_images(service_name=project_id)
    image_id = find_resource_id(images.images, image_name, "image", vm_region)

    # Catalog DBaaS codes (GRA, BHS, …) are invalid for NetworkPrivate; only the
    # companion OpenStack region is registered on the vRack network.
    private_network = ovh.cloudproject.NetworkPrivate(
        slug,
        service_name=project_id,
        name=f"sc-runner-{slug}",
        regions=[vm_region],
    )
    subnet = ovh.cloudproject.NetworkPrivateSubnet(
        f"{slug}-net",
        service_name=project_id,
        network_id=private_network.id,
        region=vm_region,
        network=PRIVATE_CIDR,
        start="10.1.0.10",
        end="10.1.0.250",
        dhcp=True,
    )
    openstack_network_id = private_network.regions_openstack_ids.apply(
        lambda ids, r=vm_region: ids.get(r, "")
    )

    plan = md.sku_tier or "essential"
    flavor = md.sku_name or md.native_id
    if flavor.startswith("postgresql-"):
        parts = flavor.split("-")
        if len(parts) >= 3:
            plan = parts[1]
            flavor = "-".join(parts[2:])

    pg_kwargs: dict = dict(
        service_name=project_id,
        engine="postgresql",
        version=str(md.engine_version),
        plan=plan,
        flavor=flavor,
        description=slug,
        deletion_protection=False,
        nodes=[
            {
                "region": region,
                "network_id": openstack_network_id,
                "subnet_id": subnet.id,
            }
        ],
        opts=ResourceOptions(
            custom_timeouts=CustomTimeouts(create="45m", delete="30m"),
            depends_on=[subnet],
        ),
    )
    if md.storage_gib:
        pg_kwargs["disk_size"] = int(md.storage_gib)

    pg = ovh.cloudproject.Database(slug, **pg_kwargs)

    admin_login = md.admin_login or "avnadmin"
    admin_user = ovh.cloudprojectdatabase.PostgresSqlUser(
        f"{slug}-admin",
        service_name=project_id,
        cluster_id=pg.id,
        name=admin_login,
        password_reset=_random_token(),
        opts=ResourceOptions(depends_on=[pg]),
    )

    db_fqdn = pg.endpoints.apply(
        lambda eps: next(
            (e.domain for e in (eps or []) if getattr(e, "domain", None)), ""
        )
    )
    db_port = pg.endpoints.apply(
        lambda eps: next(
            (int(e.port) for e in (eps or []) if getattr(e, "port", None)),
            5432,
        )
    )

    default_bindings = {
        "SC_DB_HOST": ("db", "fqdn"),
        "SC_DB_PORT": ("db", "port"),
        "SC_DB_PASSWORD": ("db", "password"),
    }
    if dbaas.client_user_data_b64 and not (
        dbaas.client_user_data_bindings or dbaas.client_user_data_template
    ):
        client_bindings: dict[str, tuple[str, str]] = {}
    else:
        client_bindings = dbaas.client_user_data_bindings or default_bindings

    client_vm_spec = VmSpec(
        role="client",
        instance=dbaas.client_instance,
        disk_gib=dbaas.client_disk_gib,
        disk_type=dbaas.client_disk_type,
        user_data_b64=dbaas.client_user_data_b64,
        user_data_template=dbaas.client_user_data_template,
        user_data_static=dbaas.client_user_data_static,
        user_data_bindings=client_bindings,
    )
    db_sources = {
        ("db", "fqdn"): db_fqdn,
        ("db", "port"): db_port.apply(lambda p: str(p) if p else "5432"),
        ("db", "password"): admin_user.password,
    }
    client_user_data = build_user_data_b64(client_vm_spec, sources=db_sources)

    client = ovh.cloudproject.Instance(
        f"{dbaas.client_instance}-client",
        service_name=project_id,
        name=f"{slug}-client"[:63],
        boot_from={"image_id": image_id},
        flavor={"flavor_id": client_flavor_id},
        network={
            "public": True,
            "private": {
                "network": {
                    "id": openstack_network_id,
                    "subnet_id": subnet.id,
                }
            },
        },
        billing_period="hourly",
        region=vm_region,
        user_data=client_user_data,
        opts=ResourceOptions(
            custom_timeouts=CustomTimeouts(create="10m"),
            depends_on=[pg, admin_user, subnet],
        ),
        **instance_opts,
    )

    export_dbaas_stack(
        spec=dbaas,
        region=region,
        zones=[region, vm_region] if vm_region != region else [region],
        db_fqdn=db_fqdn,
        db_port=db_port,
        db_bootstrap_login=admin_login,
        db_bootstrap_database="defaultdb",
        db_admin_login=admin_login,
        db_admin_password=pulumi.Output.secret(admin_user.password),
        client_private_ip=instance_ipv4(client, public=False),
        client_public_ip=instance_ipv4(client, public=True),
        storage_gib=md.storage_gib,
        network_mode=NETWORK_MODE,
    )
