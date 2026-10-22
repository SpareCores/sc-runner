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
    "ovh": "NONE",
    "upcloud": "NONE",
    "vultr": "NONE",
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


def companion_region(vendor: str, region: str) -> str:
    """Pick a compute region for a DBaaS (or other) catalog region.

    Prefer the region itself when it has ACTIVE ONDEMAND server prices; otherwise
    another ACTIVE region in the same city with compute; otherwise the nearest
    region (by lat/lon) that has compute.
    """
    stmt = text(
        """
        WITH priced AS (
            SELECT DISTINCT r.region_id, r.api_reference, r.city, r.lon, r.lat
            FROM region AS r
            JOIN server_price AS sp
              ON sp.vendor_id = r.vendor_id
             AND sp.region_id = r.region_id
            WHERE r.vendor_id = :vendor
              AND r.status = 'ACTIVE'
              AND sp.status = 'ACTIVE'
              AND sp.allocation = 'ONDEMAND'
        ),
        base AS (
            SELECT region_id, api_reference, city, lon, lat
            FROM region
            WHERE vendor_id = :vendor
              AND status = 'ACTIVE'
              AND (api_reference = :region OR region_id = :region)
            LIMIT 1
        )
        SELECT
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM priced p JOIN base b ON p.api_reference = b.api_reference
                ) THEN (SELECT api_reference FROM base)
                WHEN EXISTS (
                    SELECT 1 FROM priced p JOIN base b
                      ON p.city IS NOT NULL AND b.city IS NOT NULL AND p.city = b.city
                ) THEN (
                    SELECT p.api_reference
                    FROM priced p
                    JOIN base b ON p.city = b.city
                    ORDER BY p.api_reference
                    LIMIT 1
                )
                ELSE (
                    SELECT p.api_reference
                    FROM priced p
                    JOIN base b ON b.lon IS NOT NULL AND b.lat IS NOT NULL
                               AND p.lon IS NOT NULL AND p.lat IS NOT NULL
                    ORDER BY
                        ((p.lon - b.lon) * (p.lon - b.lon)
                         + (p.lat - b.lat) * (p.lat - b.lat)),
                        p.api_reference
                    LIMIT 1
                )
            END AS companion
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(stmt, {"vendor": vendor, "region": region}).one()
    companion = row[0]
    if not companion:
        raise ValueError(
            f"No companion compute region for {vendor}/{region} "
            "(no ACTIVE ONDEMAND server prices nearby)"
        )
    return companion


def database_storage_bounds(vendor: str, database_id: str) -> tuple[int | None, int | None]:
    """Return (min_gib, max_gib) for a managed DB SKU from sc-data.

    ``min_gib`` is ``database.storage_size``; ``max_gib`` is
    ``storage_size + storage_extra_max`` when both are present.
    """
    stmt = text(
        """
        SELECT storage_size, storage_extra_max
        FROM database
        WHERE vendor_id = :vendor
          AND (database_id = :database_id OR api_reference = :database_id)
          AND status = 'ACTIVE'
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(
            stmt, {"vendor": vendor, "database_id": database_id}
        ).one_or_none()
    if not row or row[0] is None:
        return None, None
    floor = int(row[0])
    extra = row[1]
    ceiling = floor + int(extra) if extra is not None else None
    return floor, ceiling


def database_api_reference_object(vendor: str, database_id: str) -> dict | None:
    """Return ``database.api_reference_object`` for a vendor SKU (or None)."""
    import json

    stmt = text(
        """
        SELECT api_reference_object
        FROM database
        WHERE vendor_id = :vendor
          AND (database_id = :database_id OR api_reference = :database_id)
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(
            stmt, {"vendor": vendor, "database_id": database_id}
        ).one_or_none()
    if not row or row[0] is None:
        return None
    raw = row[0]
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def upcloud_flexible_plan_meta(database_id: str) -> dict:
    """Return UpCloud rdb.* plan_storage / plan_backups from sc-data.

    Keys: ``plan_storage`` (dict with step_gib/options), ``plan_backups`` (list),
    ``plan_node_counts`` (list). Empty dicts/lists when missing.
    """
    obj = database_api_reference_object("upcloud", database_id) or {}
    return {
        "plan_storage": obj.get("plan_storage") or {},
        "plan_backups": list(obj.get("plan_backups") or []),
        "plan_node_counts": list(obj.get("plan_node_counts") or []),
    }


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
    # Vultr (and some crawls) store database_price.region_id in a different case
    # than region.region_id; join case-insensitively.
    stmt = text(
        """
        SELECT r.api_reference, dp.price
        FROM database_price AS dp
        JOIN database AS d
          ON d.vendor_id = dp.vendor_id
         AND d.database_id = dp.database_id
        JOIN region AS r
          ON r.vendor_id = dp.vendor_id
         AND LOWER(r.region_id) = LOWER(dp.region_id)
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