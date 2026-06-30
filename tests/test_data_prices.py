from sc_runner import data


def test_sort_by_price_orders_cheapest_first():
    prices = {"ewr": 0.73, "atl": 0.60, "ams": 0.58}
    assert data.sort_by_price(["ewr", "atl", "ams"], prices) == ["ams", "atl", "ewr"]


def test_sort_by_price_puts_unknown_regions_last():
    prices = {"ewr": 0.73, "atl": 0.60}
    assert data.sort_by_price(["ewr", "ord", "atl"], prices) == ["atl", "ewr", "ord"]


def test_min_prices_keeps_minimum_per_region():
    assert data._min_prices([("ewr", 0.8), ("ewr", 0.7), ("atl", 0.6)]) == {"ewr": 0.7, "atl": 0.6}
