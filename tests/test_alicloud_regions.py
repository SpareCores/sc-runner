from sc_runner.resources import alicloud as alicloud_resources


def test_cleanup_regions_unions_catalog_zones_and_plan_regions(monkeypatch):
    monkeypatch.setattr(
        alicloud_resources.data,
        "plan_regions",
        lambda vendor, instance: ["eu-central-1", "ap-southeast-1"],
    )
    zones = ["eu-central-1c", "cn-beijing-h"]
    zone_to_region = {"eu-central-1c": "eu-central-1", "cn-beijing-h": "cn-beijing"}
    assert alicloud_resources.cleanup_regions(
        "ecs.gn7i-c32g1.16xlarge",
        ["cn-beijing"],
        zones,
        zone_to_region,
    ) == ["cn-beijing", "eu-central-1", "ap-southeast-1"]
