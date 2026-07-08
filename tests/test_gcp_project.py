"""Unit tests for GCP project id resolution."""

import json
import os
from unittest.mock import patch

import pytest

from sc_runner.resources.gcp_project import gcp_project_id


def test_gcp_project_id_from_google_project_env():
    with patch.dict(
        os.environ,
        {"GOOGLE_PROJECT": "sparecores-dev", "GOOGLE_CREDENTIALS": ""},
        clear=True,
    ):
        assert gcp_project_id() == "sparecores-dev"


def test_gcp_project_id_rejects_numeric_project_number():
    creds = json.dumps({"project_id": "sparecores-dev", "type": "service_account"})
    with patch.dict(
        os.environ,
        {"GOOGLE_PROJECT": "123456789012", "GOOGLE_CREDENTIALS": creds},
        clear=True,
    ):
        assert gcp_project_id() == "sparecores-dev"


def test_gcp_project_id_rejects_display_name_with_uppercase():
    creds = json.dumps({"project_id": "sparecores-dev", "type": "service_account"})
    with patch.dict(
        os.environ,
        {"GOOGLE_PROJECT": "SpareCores Dev", "GOOGLE_CREDENTIALS": creds},
        clear=True,
    ):
        assert gcp_project_id() == "sparecores-dev"


def test_gcp_project_id_missing_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="No valid GCP project id"):
            gcp_project_id()
