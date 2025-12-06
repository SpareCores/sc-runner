from . import data
from . import resources
from . import runner
from typing import get_type_hints
import click
from click._utils import UNSET
import inspect


def add_click_opts(func):
    def inner(cmd):
        """Convert type hints into click options."""
        hints = get_type_hints(func, include_extras=True)
        for name, annotation in hints.items():
            default = inspect.signature(func).parameters[name].default
            for meta in getattr(annotation, "__metadata__", []):
                if isinstance(meta, (click.Option, click.Argument)):
                    # If the function parameter has a default, use it as the Click option default.
                    # This ensures we don't need to duplicate the default in the DefaultOpt call.
                    #
                    # Click 8.3.0+ behavior change:
                    # In Click 8.2.0 and earlier, when an option didn't have a default set,
                    # the Option.default attribute was None. However, in Click 8.3.0+, the
                    # default attribute is set to Sentinel.UNSET (from click._utils) when not
                    # explicitly provided. This change was made to better distinguish between
                    # "no default set" (UNSET) and "default explicitly set to None".
                    #
                    # The problem this caused:
                    # When we check `if not getattr(meta, "default")`, this evaluates to False
                    # for both None and UNSET (since UNSET is truthy). However, we need to
                    # explicitly check for UNSET to properly detect when a default wasn't set.
                    # Without this check, we wouldn't set the function parameter's default as
                    # the Click option default, causing Click to pass None values through
                    # Context.invoke() (as per Click 8.3.1 changelog: "Replace Sentinel.UNSET
                    # default values by None as they're passed through the Context.invoke()
                    # method"), which would override function defaults when unpacking with **kwargs.
                    #
                    # The fix:
                    # We explicitly check if meta.default is None or UNSET, and if so, we set
                    # it to the function parameter's default value. This ensures that function
                    # defaults are properly used by Click, avoiding the need to duplicate
                    # default values in both the DefaultOpt call and the function parameter.
                    meta_default = getattr(meta, "default", None)
                    if default is not inspect.Parameter.empty:
                        # Only override if meta doesn't have a non-None default explicitly set.
                        # UNSET means it wasn't set, so we should use the function default.
                        # None might also mean it wasn't set (for backward compatibility with
                        # older Click versions or explicit None defaults).
                        if meta_default is None or meta_default is UNSET:
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
def destroy_stack(**kwargs):
    """
    Destroy the underlying Pulumi stack.
    Useful if the cloud resources were deleted and the normal destroy command fails.
    """
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

    @destroy_stack.command(name=vendor)
    @click.pass_context
    def destroy_stack_cmd(ctx, **kwargs):
        pulumi_opts = ctx.parent.params
        vendor = ctx.command.name
        runner.destroy_stack(vendor, pulumi_opts, kwargs)

    @cancel.command(name=vendor)
    @click.pass_context
    def cancel_resources(ctx, **kwargs):
        pulumi_opts = ctx.parent.params
        vendor = ctx.command.name
        runner.cancel(vendor, pulumi_opts, kwargs)

    # add click options from the resource method's annotated argument list
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(create_resources)
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(destroy_resources)
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(destroy_stack_cmd)
    add_click_opts(getattr(resources, f"{resources.PREFIX}{vendor}"))(cancel_resources)


if __name__ == "__main__":
    cli()
