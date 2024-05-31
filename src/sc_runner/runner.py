from . import DefaultOpt
from . import resources
from pulumi.automation import LocalWorkspaceOptions
from pulumi.automation import ProjectBackend
from pulumi.automation import ProjectSettings
from pulumi.automation import create_or_select_stack
from typing import Annotated, Callable, get_type_hints
import click
import os


def get_stack_name(vendor: str, func: Callable, resource_opts: dict) -> str:
    hints = get_type_hints(func, include_extras=True)
    stack_name = [vendor]
    for name, annotation in hints.items():
        for meta in getattr(annotation, "__metadata__", []):
            if isinstance(meta, resources.StackName):
                stack_name.append(str(resource_opts.get(name)))
    return ".".join(stack_name)


def pulumi_stack(
    pulumi_program: Callable,
    project_name: Annotated[str, DefaultOpt(["--project-name"], type=str, help="Pulumi project name")] = os.environ.get("PULUMI_PROJECT_NAME", "runner"),
    work_dir: Annotated[str, DefaultOpt(["--work-dir"], type=str, help="Pulumi work dir")] = os.environ.get("PULUMI_WORK_DIR", "/data/workdir"),
    pulumi_home: Annotated[str, DefaultOpt(["--pulumi-home"], type=str, help="Pulumi home")] = os.environ.get("PULUMI_HOME", "/data/.pulumi"),
    pulumi_backend_url: Annotated[str, DefaultOpt(["--pulumi-backend-url"], type=str, help="Pulumi backend URL")] = os.environ.get("PULUMI_BACKEND_URL", "file:///data/backend"),
    stack_name: Annotated[
        str,
        click.Option(["--stack-name"], type=str, help="Pulumi stack name, defaults to {vendor}.{region}.{zone}.{instance_id} or similar")]
    = os.environ.get("PULUMI_STACK_NAME", ""),
):
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


def create(vendor, pulumi_opts, resource_opts):
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    def pulumi_program():
        return resource_f(**resource_opts)

    stack = pulumi_stack(pulumi_program, **pulumi_opts)
    stack.up(on_output=print)


def destroy(vendor, pulumi_opts, resource_opts):
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    stack = pulumi_stack(lambda: None, **pulumi_opts)
    stack.up(on_output=print)


def cancel(vendor, pulumi_opts, resource_opts):
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    stack = pulumi_stack(lambda: None, **pulumi_opts)
    stack.cancel()


def get_stack(vendor, pulumi_opts, resource_opts):
    resource_f = getattr(resources, f"{resources.PREFIX}{vendor}")
    pulumi_opts["stack_name"] = get_stack_name(vendor, resource_f, resource_opts)

    return pulumi_stack(lambda: None, **pulumi_opts)