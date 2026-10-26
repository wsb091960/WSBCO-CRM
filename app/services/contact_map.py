"""Build a single-contact map link without geocoding or changing CRM data."""
import math
import re
from urllib.parse import urlencode

from sqlalchemy import inspect, text

from app.gis_map import _fingerprint


def _part(value):
    value = str(value or "").strip()
    return "" if value.casefold() in {"-", "—", "n/a", "none", "unknown"} else value


def contact_map_url(db, lead):
    """Prefer a current matched GIS point; otherwise search a usable address.

    A changed address invalidates cached coordinates using the same fingerprint
    as the territory map. Reading a contact never creates the optional GIS cache.
    """
    destination = None
    if inspect(db.connection()).has_table("gis_address_points"):
        row = db.execute(text(
            "SELECT address_hash, latitude, longitude, result "
            "FROM gis_address_points WHERE lead_id = :id"
        ), {"id": lead.id}).mappings().first()
        if row and row["result"] == "matched" and row["address_hash"] == _fingerprint(lead):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
                if (math.isfinite(lat) and math.isfinite(lon)
                        and -90 <= lat <= 90 and -180 <= lon <= 180
                        and (lat != 0 or lon != 0)):
                    # ArcGIS uses x,y (longitude,latitude), unlike our GIS cache.
                    destination = f"{lon},{lat}"
            except (TypeError, ValueError):
                pass

    parameters = {
        "basemapUrl": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer",
        "mapOnly": "true",
    }
    if destination is None:
        street, city, state, zipcode = (
            _part(getattr(lead, name, ""))
            for name in ("address", "city", "state", "zip_code")
        )
        if not street or not ((city and state) or re.fullmatch(r"\d{5}(?:-\d{4})?", zipcode)):
            return None
        parameters["find"] = ", ".join(part for part in (street, city, state, zipcode) if part)
    else:
        parameters.update({"center": destination, "level": "16",
                           "marker": destination + ",4326"})

    return "https://www.arcgis.com/apps/mapviewer/index.html?" + urlencode(parameters)
