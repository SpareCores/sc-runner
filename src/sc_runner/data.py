from sc_crawler.tables import Server, ServerPrice, Datacenter, Vendor, Zone
from sqlmodel import create_engine, Session, select
import sc_data


session = Session(create_engine(f"sqlite:///{sc_data.db.path}"))


def vendors():
    return session.exec(select(Vendor.vendor_id)).all()


def regions(vendor: str):
    if vendor == "aws":
        return session.exec(select(Datacenter.datacenter_id).where(Datacenter.vendor_id == vendor)).all()
    else:
        return session.exec(select(Datacenter.name).where(Datacenter.vendor_id == vendor)).all()


def zones(vendor: str):
    return session.exec(select(Zone.name).where(Zone.vendor_id == vendor)).all()


def servers(vendor: str, region: str | None = None, zone: str | None = None):
    stmt = select(ServerPrice.server_id, Server.name).join(Zone).join(Server).where(ServerPrice.vendor_id == vendor)
    if region:
        stmt = stmt.where(ServerPrice.datacenter_id == region)
    if zone:
        stmt = stmt.where(ServerPrice.zone_id == zone)
    return [i[1] for i in session.exec(stmt.distinct()).all()]


def servers_vendors(vendor: str, region: str | None = None, zone: str | None = None):
    stmt = select(ServerPrice.vendor_id, ServerPrice.datacenter_id, Zone.name, ServerPrice.server_id).join(Zone).where(ServerPrice.vendor_id == vendor)
    if region:
        stmt = stmt.where(ServerPrice.datacenter_id == region)
    if zone:
        stmt = stmt.where(ServerPrice.zone_id == zone)
    return session.exec(stmt.distinct()).all()


def server_cpu_architecture(vendor: str, server: str) -> str:
    return session.exec(select(Server.cpu_architecture).where(Server.vendor_id == vendor).where(Server.api_reference == server)).one().value