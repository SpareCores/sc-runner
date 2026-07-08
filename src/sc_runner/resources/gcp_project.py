"""Resolve the GCP project id for Pulumi provider configuration."""

from __future__ import annotations

import json
import os
import re

_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PROJECT_ENV_KEYS = (
    "GOOGLE_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
)


def _valid_project_id(value: str) -> bool:
    value = value.strip()
    return bool(value) and _PROJECT_ID_RE.match(value) is not None


def _project_from_credentials() -> str | None:
    raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    if not raw:
        return None
    try:
        project = json.loads(raw).get("project_id", "")
    except json.JSONDecodeError:
        return None
    project = str(project).strip()
    return project if _valid_project_id(project) else None


def gcp_project_id() -> str:
    """Return a lowercase GCP project id for provider/API calls.

    Cloud SQL rejects project numbers, display names, and empty values with
    "Malformed project id ... must start with a lowercase letter". Prefer an
    explicit env var, but fall back to project_id inside GOOGLE_CREDENTIALS.
    """
    invalid: list[str] = []
    for key in _PROJECT_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if not value:
            continue
        if _valid_project_id(value):
            return value
        invalid.append(f"{key}={value!r}")

    from_credentials = _project_from_credentials()
    if from_credentials:
        return from_credentials

    detail = ", ".join(invalid) if invalid else "no GOOGLE_PROJECT*/GOOGLE_CLOUD_PROJECT* set"
    raise ValueError(
        "No valid GCP project id configured "
        f"({detail}). Set GOOGLE_PROJECT to the lowercase project id "
        "(not the numeric project number or display name)."
    )
