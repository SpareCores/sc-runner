"""Shared AWS provider / timeout helpers for sc-runner AWS stacks."""

from __future__ import annotations

import os

import pulumi_aws as aws
from pulumi import CustomTimeouts, ResourceOptions

# AWS SDK default is 25 attempts; InsufficientInstanceCapacity is treated as
# retryable and can burn ~50 minutes before failing. Cap attempts so sc-inspector
# can move to the next region/zone within a few minutes.
DEFAULT_MAX_RETRIES = 3
# Wall-clock cap after RunInstances succeeds (waiting for running state).
DEFAULT_INSTANCE_CREATE_TIMEOUT = "5m"


def aws_max_retries() -> int:
    raw = os.environ.get("AWS_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MAX_RETRIES


def instance_create_timeout() -> str:
    return (
        os.environ.get("AWS_INSTANCE_CREATE_TIMEOUT", DEFAULT_INSTANCE_CREATE_TIMEOUT).strip()
        or DEFAULT_INSTANCE_CREATE_TIMEOUT
    )


def aws_provider(
    *,
    resource_name: str,
    region: str,
    tags: dict,
    assume_role_arn: str = "",
) -> aws.Provider:
    """Provider with bounded API retries (fail capacity errors quickly)."""
    prov_kwargs: dict = {}
    if assume_role_arn:
        prov_kwargs["assume_role"] = aws.ProviderAssumeRoleArgs(role_arn=assume_role_arn)
    return aws.Provider(
        resource_name=resource_name,
        region=region,
        skip_metadata_api_check=False,  # enable instance roles
        max_retries=aws_max_retries(),
        retry_mode=os.environ.get("AWS_RETRY_MODE", "standard"),
        default_tags=aws.ProviderDefaultTagsArgs(tags=tags),
        **prov_kwargs,
    )


def instance_resource_opts(provider: aws.Provider, **extra) -> ResourceOptions:
    return ResourceOptions(
        provider=provider,
        custom_timeouts=CustomTimeouts(create=instance_create_timeout()),
        **extra,
    )
