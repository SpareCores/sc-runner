from . import DefaultOpt
from . import resources
from .cloud_meta import get_instance_id
from importlib.metadata import version, PackageNotFoundError
from pulumi.automation import Deployment
from pulumi.automation import LocalWorkspaceOptions
from pulumi.automation import ProjectBackend
from pulumi.automation import ProjectSettings
from pulumi.automation import create_or_select_stack
from typing import Annotated, Callable, get_type_hints
import click
import copy
import os
import sentry_sdk


def get_installed_package_version(package_name: str) -> str:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return f"Package '{package_name}' is not installed."

instance_id, cloud_provider = get_instance_id()
sentry_sdk.set_context("cloud_metadata", {"instance-id": instance_id, "cloud-provider": cloud_provider})
sentry_sdk.init(release=get_installed_package_version("sparecores-runner"))


def get_stack_name(vendor: str, func: Callable, resource_opts: dict) -> str:
    hints = get_type_hints(func, include_extras=True)
    stack_name = [vendor]
    for name, annotation in hints.items():
        for meta in getattr(annotation, "__metadata__", []):
            # if an option is annotated as StackName, it will be included in the stack name
            if isinstance(meta, resources.StackName):
                stack_name.append(str(resource_opts.get(name)))
    return ".".join(stack_name)


def pulumi_stack(
    pulumi_program: Callable,
    project_name: Annotated[str, DefaultOpt(["--project-name"], type=str, help="Pulumi project name")] = os.environ.get("PULUMI_PROJECT_NAME", "runner"),
    work_dir: Annotated[str, DefaultOpt(["--work-dir"], type=str, help="Pulumi work dir")] = os.environ.get("PULUMI_WORK_DIR", "/data/workdir"),
    pulumi_home: Annotated[str, DefaultOpt(["--pulumi-home"], type=str, help="Pulumi home")] = os.environ.get("PULUMI_HOME", "/root/.pulumi"),
    pulumi_backend_url: Annotated[str, DefaultOpt(["--pulumi-backend-url"], type=str, help="Pulumi backend URL")] = os.environ.get("PULUMI_BACKEND_URL", "file:///data/backend"),
    stack_name: Annotated[
        str,
        click.Option(["--stack-name"], type=str, help="Pulumi stack name, defaults to {vendor}.{region}.{zone}.{instance_id} or similar")]
    = os.environ.get("PULUMI_STACK_NAME", ""),
):
    sentry_sdk.set_context("pulumi", {
        "project_name": project_name,
        "work_dir": work_dir,
        "pulumi_home": pulumi_home,
        "pulumi_backend_url": pulumi_backend_url,
        "stack_name": stack_name,
    })
    stack = create_or_select_stack(
        stack_name=stack_name,
        project_name=project_name,
        program=pulumi_program,
        opts=LocalWorkspaceOptions(
            work_dir=work_dir,
            pulumi_home=pulumi_home,
            project_settings=ProjectSettings(
                name=project_name,
                runtime="python",
                backend=ProjectBackend(pulumi_backend_url)
            )))
    return stack


def create(vendor, pulumi_opts, resource_opts, stack_opts=dict(on_output=print)):
    # don't modify incoming opts
    pulumi_opts = copy.deepcopy(pulumi_opts)
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    if not pulumi_opts.get("stack_name"):
        pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    def pulumi_program():
        return resource_f(**resource_opts)

    stack = pulumi_stack(pulumi_program, **pulumi_opts)
    stack.up(**stack_opts)


def destroy(vendor, pulumi_opts, resource_opts, stack_opts=dict(on_output=print)):
    # don't modify incoming opts
    pulumi_opts = copy.deepcopy(pulumi_opts)
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    if not pulumi_opts.get("stack_name"):
        pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    stack = pulumi_stack(lambda: None, **pulumi_opts)
    stack.up(**stack_opts)


_MISSING_CLOUD_RESOURCE_MARKERS = (
    "instance not found",
    "server not found",
    '"status":404',
    "status\":404",
    "error getting instance",
    "error getting bare metal",
    "error destroying instance",
    "error destroying ssh",
    "invalid instance-id",
    "invalid instance id",
    "invalidinstanceid.notfound",
    "invalidsecuritygroupid.notfound",
    "incorrectinstancestatus",
)


def _exception_text(exc: BaseException) -> str:
    parts = [str(exc)]
    for attr in ("stdout", "stderr", "message"):
        val = getattr(exc, attr, None)
        if val:
            parts.append(str(val))
    if exc.__cause__:
        parts.append(_exception_text(exc.__cause__))
    return "\n".join(parts)


def _missing_cloud_resource_failure(exc: BaseException) -> bool:
    text = _exception_text(exc).lower()
    return any(marker in text for marker in _MISSING_CLOUD_RESOURCE_MARKERS)


def _refresh_failed_due_to_missing_resource(exc: BaseException) -> bool:
    return _missing_cloud_resource_failure(exc)


def _refresh_stack(stack, stack_opts):
    on_output = stack_opts.get("on_output", print)
    try:
        stack.refresh(**stack_opts)
    except Exception as exc:
        if not _missing_cloud_resource_failure(exc):
            raise
        on_output(
            "Refresh reported missing cloud resource(s); continuing with destroy "
            f"({exc})"
        )


def _pruned_stack_resources(resources: list) -> list:
    """Keep only the stack record and non-custom resources after ghost pruning."""
    return [
        res
        for res in resources
        if res.get("type") == "pulumi:pulumi:Stack" or not res.get("custom", True)
    ]


def _custom_resource_urns(stack) -> list[str]:
    deployment = stack.export_stack()
    resources = deployment.deployment.get("resources", [])
    return [
        res["urn"]
        for res in resources
        if res.get("urn")
        and res.get("type") != "pulumi:pulumi:Stack"
        and res.get("custom", True)
    ]


def _prune_custom_resources_from_state(stack, stack_opts) -> bool:
    """Drop provider-managed resources from state when the cloud copy is already gone."""
    on_output = stack_opts.get("on_output", print)
    exported = stack.export_stack()
    resources = exported.deployment.get("resources", [])
    pruned = _pruned_stack_resources(resources)
    removed = len(resources) - len(pruned)
    if not removed:
        return False
    on_output(f"Removing {removed} ghost resource(s) from Pulumi state")
    deployment = copy.deepcopy(exported.deployment)
    deployment["resources"] = pruned
    stack.import_stack(Deployment(version=exported.version, deployment=deployment))
    return True


def _destroy_stack(stack, stack_opts) -> bool:
    """Destroy stack resources. Returns True if stack removal should use --force."""
    on_output = stack_opts.get("on_output", print)
    try:
        stack.destroy(**stack_opts)
        return False
    except Exception as exc:
        if not _missing_cloud_resource_failure(exc):
            raise
        on_output(
            "Destroy reported missing cloud resource(s); pruning from state "
            f"({exc})"
        )

    if not _custom_resource_urns(stack):
        return False

    _prune_custom_resources_from_state(stack, stack_opts)
    try:
        stack.destroy(**stack_opts)
        return False
    except Exception as exc:
        if not _missing_cloud_resource_failure(exc):
            raise
        on_output(
            "Destroy still reports missing resources after state prune; "
            f"force-removing stack ({exc})"
        )
        return True


def destroy_stack(vendor, pulumi_opts, resource_opts, stack_opts=dict(on_output=print)):
    # don't modify incoming opts
    pulumi_opts = copy.deepcopy(pulumi_opts)
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    if not pulumi_opts.get("stack_name"):
        pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    stack = pulumi_stack(lambda: None, **pulumi_opts)
    _refresh_stack(stack, stack_opts)
    force_remove = _destroy_stack(stack, stack_opts)
    stack.workspace.remove_stack(stack.name, force=force_remove)


def cancel(vendor, pulumi_opts, resource_opts):
    # don't modify incoming opts
    pulumi_opts = copy.deepcopy(pulumi_opts)
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    if not pulumi_opts.get("stack_name"):
        pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    stack = pulumi_stack(lambda: None, **pulumi_opts)
    stack.cancel()


def get_stack(vendor, pulumi_opts, resource_opts):
    # don't modify incoming opts
    pulumi_opts = copy.deepcopy(pulumi_opts)
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    if not pulumi_opts.get("stack_name"):
        pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    return pulumi_stack(lambda: None, **pulumi_opts)
