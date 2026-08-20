from sc_crawler.tables import Server, ServerPrice, Region, Vendor, Zone
from sqlalchemy import text
from sqlmodel import create_engine, Session, select
import sc_data


_engine = create_engine(f"sqlite:///{sc_data.db.path}")
session = Session(_engine)

# database_price.ha for non-HA (standalone) deploys. AWS Single-AZ is SINGLE_ZONE.
_DBAAS_STANDALONE_PRICE_HA = {
    "aws": "SINGLE_ZONE",
    "azure": "NONE",
    "gcp": "NONE",
}


def vendors():
    return session.exec(select(Vendor.vendor_id)).all()


def regions(vendor: str):
    return session.exec(select(Region.api_reference).where(Region.vendor_id == vendor)).all()


def zones(vendor: str):
    return session.exec(select(Zone.api_reference).where(Zone.vendor_id == vendor)).all()


def plan_regions(vendor: str, server: str) -> list[str]:
    """Return region api_reference values where server has ACTIVE ONDEMAND prices."""
    stmt = (
        select(Region.api_reference)
        .join(
            ServerPrice,
            (ServerPrice.vendor_id == Region.vendor_id)
            & (ServerPrice.region_id == Region.region_id),
        )
        .join(
            Server,
            (Server.vendor_id == ServerPrice.vendor_id)
            & (Server.server_id == ServerPrice.server_id),
        )
        .where(ServerPrice.vendor_id == vendor)
        .where(Server.api_reference == server)
        .where(Server.status == "ACTIVE")
        .where(ServerPrice.status == "ACTIVE")
        .where(ServerPrice.allocation == "ONDEMAND")
        .distinct()
        .order_by(Region.api_reference)
    )
    return list(session.exec(stmt).all())


def _min_prices(rows: list[tuple[str, float]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for key, price in rows:
        if key not in prices or price < prices[key]:
            prices[key] = price
    return prices


def server_region_prices(vendor: str, server: str) -> dict[str, float]:
    """Return minimum ACTIVE ONDEMAND hourly price per region api_reference."""
    stmt = (
        select(Region.api_reference, ServerPrice.price)
        .join(
            ServerPrice,
            (ServerPrice.vendor_id == Region.vendor_id)
            & (ServerPrice.region_id == Region.region_id),
        )
        .join(
            Server,
            (Server.vendor_id == ServerPrice.vendor_id)
            & (Server.server_id == ServerPrice.server_id),
        )
        .where(ServerPrice.vendor_id == vendor)
        .where(Server.api_reference == server)
        .where(Server.status == "ACTIVE")
        .where(ServerPrice.status == "ACTIVE")
        .where(ServerPrice.allocation == "ONDEMAND")
    )
    return _min_prices(session.exec(stmt).all())


def server_zone_prices(vendor: str, server: str) -> dict[str, float]:
    """Return minimum ACTIVE ONDEMAND hourly price per zone api_reference."""
    stmt = (
        select(Zone.api_reference, ServerPrice.price)
        .join(
            ServerPrice,
            (ServerPrice.vendor_id == Zone.vendor_id)
            & (ServerPrice.region_id == Zone.region_id)
            & (ServerPrice.zone_id == Zone.zone_id),
        )
        .join(
            Server,
            (Server.vendor_id == ServerPrice.vendor_id)
            & (Server.server_id == ServerPrice.server_id),
        )
        .where(ServerPrice.vendor_id == vendor)
        .where(Server.api_reference == server)
        .where(Server.status == "ACTIVE")
        .where(ServerPrice.status == "ACTIVE")
        .where(ServerPrice.allocation == "ONDEMAND")
    )
    return _min_prices(session.exec(stmt).all())


def sort_by_price(keys: list[str], prices: dict[str, float]) -> list[str]:
    """Sort location keys cheapest-first using sc-data hourly prices."""
    return sorted(keys, key=lambda key: (prices.get(key, float("inf")), key))


def database_region_prices(
    vendor: str,
    database_id: str,
    *,
    ha: str | None = None,
) -> dict[str, float]:
    """Return minimum ACTIVE ONDEMAND hourly price per region api_reference.

    ``database_id`` may be the catalog ``database_id`` or ``api_reference``.
    ``ha`` defaults to the vendor's standalone price HA key (AWS: SINGLE_ZONE).
    """
    price_ha = ha or _DBAAS_STANDALONE_PRICE_HA.get(vendor, "NONE")
    stmt = text(
        """
        SELECT r.api_reference, dp.price
        FROM database_price AS dp
        JOIN database AS d
          ON d.vendor_id = dp.vendor_id
         AND d.database_id = dp.database_id
        JOIN region AS r
          ON r.vendor_id = dp.vendor_id
         AND r.region_id = dp.region_id
        WHERE dp.vendor_id = :vendor
          AND (d.database_id = :database_id OR d.api_reference = :database_id)
          AND d.status = 'ACTIVE'
          AND dp.status = 'ACTIVE'
          AND dp.allocation = 'ONDEMAND'
          AND dp.ha = :price_ha
        """
    )
    with _engine.connect() as conn:
        return _min_prices(
            list(
                conn.execute(
                    stmt,
                    {
                        "vendor": vendor,
                        "database_id": database_id,
                        "price_ha": price_ha,
                    },
                ).all()
            )
        )


def servers(vendor: str, region: str | None = None, zone: str | None = None):
    stmt = select(ServerPrice.server_id, Server.api_reference).join(Zone).join(Server).where(ServerPrice.vendor_id == vendor)
    if region:
        stmt = stmt.where(ServerPrice.region_id == region)
    if zone:
        stmt = stmt.where(ServerPrice.zone_id == zone)
    return [i[1] for i in session.exec(stmt.distinct()).all()]


def servers_vendors(vendor: str, region: str | None = None, zone: str | None = None):
    stmt = select(ServerPrice.vendor_id, ServerPrice.region_id, Zone.api_reference, ServerPrice.server_id).join(Zone).where(ServerPrice.vendor_id == vendor)
    if region:
        stmt = stmt.where(ServerPrice.region_id == region)
    if zone:
        stmt = stmt.where(ServerPrice.zone_id == zone)
    return session.exec(stmt.distinct()).all()


def server_cpu_architecture(vendor: str, server: str) -> str:
    return session.exec(select(Server.cpu_architecture).where(Server.vendor_id == vendor).where(Server.api_reference == server)).one().value


def hcloud_location(region: str) -> str:
    """Map a Hetzner datacenter (api_reference) or region_id to a location name."""
    row = session.exec(
        select(Region)
        .where(Region.vendor_id == "hcloud")
        .where((Region.api_reference == region) | (Region.region_id == region))
    ).first()
    if row and row.aliases:
        return row.aliases[0]
    if "-dc" in region:
        return region.split("-dc", 1)[0]
    return region