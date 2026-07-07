"""Unit tests for Azure DBaaS stack spec (no live Azure required)."""

from sc_runner.resources.managed_db import DbaasStackSpec, ManagedDbSpec


def test_managed_db_spec_defaults():
    spec = ManagedDbSpec(
        native_id="Standard_E16ds_v5",
        sku_name="Standard_E16ds_v5",
        sku_tier="MemoryOptimized",
    )
    assert spec.engine == "postgres"
    assert spec.engine_version == "18"
    assert spec.storage_gib == 128


def test_dbaas_stack_spec():
    md = ManagedDbSpec(
        native_id="Standard_E16ds_v5",
        sku_name="Standard_E16ds_v5",
        sku_tier="MemoryOptimized",
        storage_gib=128,
        storage_iops_tier="P30",
    )
    stack = DbaasStackSpec(
        managed_db=md,
        client_instance="Standard_F8ams_v6",
        instance_key_slug="e16dsv5-pg18-c100",
        client_user_data_b64="IyEvYmluL2Jhc2g=",
    )
    assert stack.topology == "dbaas"
    assert stack.client_instance == "Standard_F8ams_v6"
    assert stack.instance_key_slug == "e16dsv5-pg18-c100"
