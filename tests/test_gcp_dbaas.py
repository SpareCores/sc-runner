"""Unit tests for GCP DBaaS helpers (no live GCP required)."""

from sc_runner.resources.gcp_dbaas import _postgres_version, _sql_instance_name


def test_postgres_version_major_only():
    assert _postgres_version("18") == "POSTGRES_18"
    assert _postgres_version("18.4") == "POSTGRES_18"


def test_sql_instance_name_sanitized():
    name = _sql_instance_name("perfoptn16-pg18-c100")
    assert name.startswith("sc-")
    assert name == name.lower()
    assert len(name) <= 98
