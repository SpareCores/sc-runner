import base64
from dataclasses import dataclass, field
from typing import Any

import pulumi

_TEMPLATE_META_KEYS = frozenset({"USER_DATA_TEMPLATE", "USER_DATA_TEMPLATE_B64"})


@dataclass
class VmSpec:
    """One VM in a multi-VM Pulumi stack."""

    role: str
    instance: str
    disk_gib: int = 30
    # Optional storage tier for this VM. Values are provider-native (e.g. Azure
    # "Premium_LRS", GCP "pd-ssd", AWS "gp3"); left None the provider default is used.
    disk_type: str | None = None
    disk_iops: int | None = None
    disk_throughput: int | None = None
    user_data_b64: str | None = None
    user_data_template: str | None = None
    user_data_static: dict[str, str] = field(default_factory=dict)
    # placeholder name -> (source role, output attribute), e.g. ("client", "private_ip")
    user_data_bindings: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass
class VmOutputs:
    """Network and instance identifiers exported from a provisioned VM."""

    instance: str
    private_ip: pulumi.Input[str]
    public_ip: pulumi.Input[str]
    zone: pulumi.Input[str] | None = None


@dataclass
class MultiVmStackSpec:
    """Specification for provisioning two or more VMs as one Pulumi stack."""

    primary_role: str
    vms: dict[str, VmSpec]
    boot_order: list[str] | None = None
    topology: str = "multi_vm"
    extra_exports: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.primary_role not in self.vms:
            raise ValueError(f"primary_role {self.primary_role!r} not in vms")
        if self.boot_order is None:
            self.boot_order = list(self.vms.keys())

    def vm(self, role: str) -> VmSpec:
        return self.vms[role]

    # Convenience accessors for the two-VM db/client topology (the only shape in use).
    @property
    def db_instance(self) -> str:
        return self.vms[self.primary_role].instance

    @property
    def client_instance(self) -> str:
        return self.vms["client"].instance

    @property
    def db_disk_gib(self) -> int:
        return self.vms[self.primary_role].disk_gib

    @property
    def client_disk_gib(self) -> int:
        return self.vms["client"].disk_gib

    @property
    def db_disk_type(self) -> str | None:
        return self.vms[self.primary_role].disk_type

    @property
    def db_disk_iops(self) -> int | None:
        return self.vms[self.primary_role].disk_iops

    @property
    def db_disk_throughput(self) -> int | None:
        return self.vms[self.primary_role].disk_throughput

    @property
    def client_disk_type(self) -> str | None:
        return self.vms["client"].disk_type

    @property
    def client_user_data_b64(self) -> str:
        return self.vms["client"].user_data_b64 or ""

    @classmethod
    def two_vm(
        cls,
        *,
        primary_role: str = "db",
        client_role: str = "client",
        primary_instance: str,
        client_instance: str,
        primary_disk_gib: int,
        client_disk_gib: int = 30,
        primary_disk_type: str | None = None,
        primary_disk_iops: int | None = None,
        primary_disk_throughput: int | None = None,
        client_disk_type: str | None = None,
        client_user_data_b64: str,
        primary_user_data_template: str,
        primary_user_data_static: dict[str, str] | None = None,
        primary_user_data_bindings: dict[str, tuple[str, str]] | None = None,
        boot_order: list[str] | None = None,
        topology: str = "multi_vm",
        extra_exports: dict[str, Any] | None = None,
    ) -> "MultiVmStackSpec":
        bindings = primary_user_data_bindings or {
            "CLIENT_PRIVATE_IP": (client_role, "private_ip"),
        }
        return cls(
            primary_role=primary_role,
            vms={
                client_role: VmSpec(
                    role=client_role,
                    instance=client_instance,
                    disk_gib=client_disk_gib,
                    disk_type=client_disk_type,
                    user_data_b64=client_user_data_b64,
                ),
                primary_role: VmSpec(
                    role=primary_role,
                    instance=primary_instance,
                    disk_gib=primary_disk_gib,
                    disk_type=primary_disk_type,
                    disk_iops=primary_disk_iops,
                    disk_throughput=primary_disk_throughput,
                    user_data_template=primary_user_data_template,
                    user_data_static=primary_user_data_static or {},
                    user_data_bindings=bindings,
                ),
            },
            boot_order=boot_order or [client_role, primary_role],
            topology=topology,
            extra_exports=extra_exports or {},
        )


def render_user_data(template: str, replacements: dict[str, Any]) -> str:
    """Substitute {PLACEHOLDER} tokens in a user-data shell script template."""
    rendered = template
    for key, value in replacements.items():
        if key in _TEMPLATE_META_KEYS:
            continue
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def render_user_data_from_replacements(replacements: dict[str, Any]) -> str:
    """Render user-data from a replacements dict (includes USER_DATA_TEMPLATE key)."""
    template = replacements.get("USER_DATA_TEMPLATE")
    if template is None:
        template_b64 = replacements.get("USER_DATA_TEMPLATE_B64")
        if template_b64 is None:
            raise ValueError(
                "replacements must include USER_DATA_TEMPLATE or USER_DATA_TEMPLATE_B64"
            )
        template = base64.b64decode(template_b64).decode("utf-8")
    return render_user_data(template, replacements)


# Backward-compatible alias.
render_server_user_data = render_user_data_from_replacements


def _encode_user_data(script: str) -> str:
    return base64.b64encode(script.encode("utf-8")).decode("ascii")


def build_user_data_b64(
    vm: VmSpec,
    *,
    sources: dict[tuple[str, str], pulumi.Input[str]] | None = None,
) -> pulumi.Output[str] | str:
    """Build base64 user-data for one VM, resolving dynamic bindings from peer outputs.

    sources maps (role, attribute) -> Pulumi output, e.g. {("client", "private_ip"): ip}.
    """
    if vm.user_data_b64 and not vm.user_data_bindings and not vm.user_data_template:
        return vm.user_data_b64

    template = vm.user_data_template
    if not template:
        template = vm.user_data_static.get("USER_DATA_TEMPLATE")
        if not template:
            raise ValueError(
                f"VM {vm.role!r}: user_data_template required when bindings are used"
            )

    static = {k: v for k, v in vm.user_data_static.items() if k != "USER_DATA_TEMPLATE"}

    if not vm.user_data_bindings:
        return _encode_user_data(render_user_data(template, static))

    sources = sources or {}
    binding_items: list[tuple[str, pulumi.Input[str]]] = []
    for placeholder, ref in vm.user_data_bindings.items():
        if ref not in sources:
            raise ValueError(
                f"VM {vm.role!r}: missing source for binding {placeholder!r} -> {ref}"
            )
        binding_items.append((placeholder, sources[ref]))

    if len(binding_items) == 1:
        placeholder, source = binding_items[0]
        return pulumi.Output.from_input(source).apply(
            lambda value: _encode_user_data(
                render_user_data(template, {**static, placeholder: value})
            )
        )

    placeholders = [ph for ph, _ in binding_items]
    inputs = [src for _, src in binding_items]
    return pulumi.Output.all(*inputs).apply(
        lambda values: _encode_user_data(
            render_user_data(template, {**static, **dict(zip(placeholders, values))})
        )
    )


def build_server_user_data_b64(
    spec: MultiVmStackSpec,
    client_private_ip: pulumi.Input[str],
) -> pulumi.Output[str]:
    """Render primary-role user-data with peer outputs injected for the two-VM topology."""
    primary = spec.vms[spec.primary_role]
    sources: dict[tuple[str, str], pulumi.Input[str]] = {}
    for ref in set(primary.user_data_bindings.values()):
        if ref == ("client", "private_ip"):
            sources[ref] = client_private_ip
    return build_user_data_b64(primary, sources=sources)


def export_multi_vm_stack(
    *,
    spec: MultiVmStackSpec,
    db_private_ip: pulumi.Input[str],
    client_private_ip: pulumi.Input[str],
    db_public_ip: pulumi.Input[str],
    client_public_ip: pulumi.Input[str],
    region: pulumi.Input[str],
    zones: pulumi.Input[list[str]],
    provisioned_disk_gib: int,
    client_disk_gib: int,
    db_disk_type: str | None = None,
    db_disk_iops: int | None = None,
    db_disk_throughput: int | None = None,
) -> None:
    """Export stack outputs for a two-VM client/db topology."""
    vms = {
        "client": VmOutputs(
            instance=spec.client_instance,
            private_ip=client_private_ip,
            public_ip=client_public_ip,
        ),
        spec.primary_role: VmOutputs(
            instance=spec.db_instance,
            private_ip=db_private_ip,
            public_ip=db_public_ip,
        ),
    }
    _export_stack(
        spec=spec,
        vms=vms,
        region=region,
        zones=zones,
        extra_exports={
            "provisioned_disk_gib": provisioned_disk_gib,
            "client_disk_gib": client_disk_gib,
            "db_disk_type": db_disk_type,
            "db_disk_iops": db_disk_iops,
            "db_disk_throughput": db_disk_throughput,
        },
    )


def _export_stack(
    *,
    spec: MultiVmStackSpec,
    vms: dict[str, VmOutputs],
    region: pulumi.Input[str],
    zones: pulumi.Input[list[str]],
    extra_exports: dict[str, Any],
) -> None:
    pulumi.export("topology", spec.topology)
    pulumi.export("primary_role", spec.primary_role)
    pulumi.export("region", region)
    pulumi.export("zones", zones)

    for role, out in vms.items():
        pulumi.export(f"{role}_instance", out.instance)
        pulumi.export(f"{role}_private_ip", out.private_ip)
        pulumi.export(f"{role}_public_ip", out.public_ip)
        if out.zone is not None:
            pulumi.export(f"{role}_zone", out.zone)

    for key, value in extra_exports.items():
        pulumi.export(key, value)
