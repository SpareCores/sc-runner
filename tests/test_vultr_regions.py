from sc_runner.resources import vultr as vultr_resources


def test_cleanup_regions_unions_catalog_and_deployable_plan_regions(monkeypatch):
    monkeypatch.setattr(
        vultr_resources,
        "filter_regions",
        lambda instance, regions, disk_size=30: ["ewr", "ord"] if not regions else ["atl"],
    )
    assert vultr_resources.cleanup_regions("vx1-g-48c-192g", ["atl"], disk_size=128) == [
        "atl",
        "ewr",
        "ord",
    ]
