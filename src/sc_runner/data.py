from sc_crawler.tables import Server, ServerPrice, Region, Vendor, Zone
from sqlmodel import create_engine, Session, select
import sc_data


session = Session(create_engine(f"sqlite:///{sc_data.db.path}"))


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