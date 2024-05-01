import click
import json


class DefaultOpt(click.Option):
    def __init__(self, *args, **kwargs):
        kwargs["show_default"] = True
        super().__init__(*args, **kwargs)


class JsonParamType(click.ParamType):
    name = "json"

    def convert(self, value, param, ctx):
        try:
            return json.loads(value)
        except ValueError:
            self.fail(f"{value!r} is not a valid JSON!", param, ctx)


JSON = JsonParamType()