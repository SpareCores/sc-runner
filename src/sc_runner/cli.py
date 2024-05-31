from . import data
from . import resources
from . import runner
from typing import get_type_hints
import click
import inspect


def add_click_opts(func):
    def inner(cmd):
        """Convert type hints into click options."""
        hints = get_type_hints(func, include_extras=True)
        for name, annotation in hints.items():
            default = inspect.signature(func).parameters[name].default
            for meta in getattr(annotation, "__metadata__", []):
                if isinstance(meta, (click.Option, click.Argument)):
                    # if no default is set in the click Option, and there's one specified as
                    # the parameter's default, set it as click option default
                    if not getattr(meta, "default") and default is not inspect.Parameter.empty:
                        meta.default = default
                    if meta.name != name:
                        # in case of a different argument and click option name, replace the
                        # click.Option's name, so it will be mapped correctly
                        # _type: Annotated[str, DefaultOpt(["--type"])
                        meta.name = name
                    cmd.params.append(meta)
        return cmd
    return inner


@click.group()
def cli():
    pass


@add_click_opts(runner.pulumi_stack)
@cli.group()
def create(**kwargs):
    pass


@add_click_opts(runner.pulumi_stack)
@cli.group()
def destroy(**kwargs):
    pass


@add_click_opts(runner.pulumi_stack)
@cli.group()
def cancel(**kwargs):
    pass


for vendor in data.vendors():
    if vendor not in resources.supported_vendors:
        # exclude not yet supported vendors
        continue

    @create.command(name=vendor)
    @click.pass_context
    def create_resources(ctx, **kwargs):
        pulumi_opts = ctx.parent.params
        vendor = ctx.command.name
        runner.create(vendor, pulumi_opts, kwargs)

    @destroy.command(name=vendor)
    @click.pass_context
    def destroy_resources(ctx, **kwargs):
        pulumi_opts = ctx.parent.params
        vendor = ctx.command.name
        runner.destroy(vendor, pulumi_opts, kwargs)

    @cancel.command(name=vendor)
    @click.pass_context
    def cancel_resources(ctx, **kwargs):
        pulumi_opts = ctx.parent.params
        vendor = ctx.command.name
        runner.cancel(vendor, pulumi_opts, kwargs)

    # add click options from the resource method's annotated argument list
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(create_resources)
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(destroy_resources)
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(cancel_resources)


if __name__ == "__main__":
    cli()
