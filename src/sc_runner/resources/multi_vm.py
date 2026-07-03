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

    @property
    def primary_instance(self) -> str:
        return self.vms[self.primary_role].instance

    # Legacy accessors for the common client + primary (db/server) two-VM pattern.
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
    def client_user_data_b64(self) -> str:
        return self.vms["client"].user_data_b64 or ""

    @property
    def server_user_data_replacements(self) -> dict[str, Any] | None:
        primary = self.vms[self.primary_role]
        if not primary.user_data_template and not primary.user_data_static:
            return None
        out: dict[str, Any] = dict(primary.user_data_static)
        if primary.user_data_template:
            out["USER_DATA_TEMPLATE"] = primary.user_data_template
        return out

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
                    user_data_b64=client_user_data_b64,
                ),
                primary_role: VmSpec(
                    role=primary_role,
                    instance=primary_instance,
                    disk_gib=primary_disk_gib,
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
    """Render primary-role user-data with peer outputs injected (legacy two-VM helper)."""
    primary = spec.vms[spec.primary_role]
    sources: dict[tuple[str, str], pulumi.Input[str]] = {}
    for ref in set(primary.user_data_bindings.values()):
        if ref == ("client", "private_ip"):
            sources[ref] = client_private_ip
    return build_user_data_b64(primary, sources=sources)


def export_stack(
    *,
    spec: MultiVmStackSpec,
    vms: dict[str, VmOutputs],
    region: pulumi.Input[str],
    zones: pulumi.Input[list[str]],
    extra_exports: dict[str, Any] | None = None,
) -> None:
    """Export generic multi-VM stack outputs ({role}_private_ip, etc.)."""
    _export_stack(
        spec=spec,
        vms=vms,
        region=region,
        zones=zones,
        extra_exports={**spec.extra_exports, **(extra_exports or {})},
    )


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
) -> None:
    """Export stack outputs for a two-VM client/db topology (legacy entry point)."""
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

    # Legacy aliases for client/db inspector stacks.
    if spec.primary_role in vms:
        primary = vms[spec.primary_role]
        pulumi.export("db_instance", primary.instance)
        pulumi.export("db_private_ip", primary.private_ip)
        pulumi.export("db_public_ip", primary.public_ip)
    if "client" in vms:
        client = vms["client"]
        pulumi.export("client_instance", client.instance)
        pulumi.export("client_private_ip", client.private_ip)
        pulumi.export("client_public_ip", client.public_ip)

    for key, value in extra_exports.items():
        pulumi.export(key, value)
