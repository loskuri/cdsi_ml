import time
import re
from datetime import datetime, date
from math import radians, cos, sin, asin, sqrt
from loguru import logger
import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from config import (
    ML_API_BASE, ML_SITE, ML_REAL_ESTATE_CAT, ML_PROPERTY_TYPES,
    REQUEST_DELAY, OBELISK_LAT, OBELISK_LON,
)
from storage.database import upsert_property, save_images, mark_sold_or_removed
from storage.images import download_images


def _haversine_m(lat1, lon1, lat2, lon2) -> int:
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return int(2 * R * asin(sqrt(a)))


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(re.sub(r"[^\d]", "", str(val)))
    except ValueError:
        return None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(re.sub(r"[^\d.]", "", str(val).replace(",", ".")))
    except ValueError:
        return None


def _bool_feature(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


def _attr(attributes: list[dict], attr_id: str):
    for a in attributes:
        if a.get("id") == attr_id:
            return a.get("value_name") or a.get("values", [{}])[0].get("name")
    return None


def _calculate_quality_score(prop: dict) -> float:
    score = 0
    if prop.get("price"):       score += 20
    if prop.get("total_sqm"):   score += 15
    if prop.get("covered_sqm"): score += 10
    if prop.get("rooms"):       score += 10
    if prop.get("latitude"):    score += 15
    if prop.get("description"): score += 10
    photos = prop.get("photos_count") or 0
    score += min(photos * 2, 20)
    return round(score, 2)


def _computed_fields(prop: dict) -> dict:
    price = prop.get("price")
    cov   = prop.get("covered_sqm")
    total = prop.get("total_sqm")
    rooms = prop.get("rooms")
    lat   = prop.get("latitude")
    lon   = prop.get("longitude")

    prop["price_per_sqm_covered"] = round(price / cov, 2)   if price and cov   else None
    prop["price_per_sqm_total"]   = round(price / total, 2) if price and total else None
    prop["price_per_room"]        = round(price / rooms, 2) if price and rooms else None
    prop["ratio_covered_total"]   = round(cov / total, 4)   if cov and total   else None
    prop["distance_to_obelisk_m"] = _haversine_m(lat, lon, OBELISK_LAT, OBELISK_LON) if lat and lon else None

    published = prop.get("published_at")
    if published:
        d = published if isinstance(published, date) else published.date()
        prop["days_on_market"] = (date.today() - d).days

    prop["listing_quality_score"] = _calculate_quality_score(prop)
    return prop


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def _get(client: httpx.Client, url: str, params: dict = None) -> dict:
    resp = client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _search_page(client: httpx.Client, category: str, offset: int) -> dict:
    return _get(client, f"{ML_API_BASE}/sites/{ML_SITE}/search", params={
        "category":   category,
        "state":      "TUxBUENBUGw3M2JR",
        "condition":  "not_specified",
        "limit":      50,
        "offset":     offset,
    })


def _get_item(client: httpx.Client, item_id: str) -> dict:
    return _get(client, f"{ML_API_BASE}/items/{item_id}")


def _get_description(client: httpx.Client, item_id: str) -> str:
    try:
        data = _get(client, f"{ML_API_BASE}/items/{item_id}/description")
        return data.get("plain_text", "")
    except Exception:
        return ""


def _detect_sale_status(item: dict) -> tuple[str, datetime | None]:
    status     = item.get("status", "active")
    sub_status = item.get("sub_status", [])

    if status == "closed":
        if item.get("sold_quantity", 0) > 0:
            return "sold", datetime.now()
        return "removed", None

    if status in ("inactive", "paused") or "deleted" in sub_status:
        return "removed", None

    return "active", None


def _parse_item(item: dict, prop_type: str, description: str) -> dict:
    attrs   = item.get("attributes", [])
    geo     = item.get("geolocation") or {}
    loc     = item.get("location") or {}
    seller  = item.get("seller") or {}
    price   = item.get("price")
    currency = item.get("currency_id", "USD")

    images = [p.get("url", "").replace("-O.", "-F.") for p in item.get("pictures", []) if p.get("url")]

    expenses_raw = next((
        a.get("value_name") for a in attrs if a.get("id") == "MAINTENANCE_FEE"
    ), None)

    pub_date = item.get("date_created")
    if pub_date:
        try:
            pub_date = datetime.fromisoformat(pub_date[:19])
        except Exception:
            pub_date = None

    prop = {
        "source":           "mercadolibre",
        "source_id":        item.get("id"),
        "url":              item.get("permalink"),
        "title":            item.get("title"),
        "description":      description,
        "property_type":    prop_type,
        "operation_type":   "venta",
        "status":           _attr(attrs, "PROPERTY_CONDITION"),
        "price":            _parse_float(price),
        "currency":         currency,
        "expenses":         _parse_float(expenses_raw),
        "expenses_currency": currency,
        "total_sqm":        _parse_float(_attr(attrs, "TOTAL_AREA")),
        "covered_sqm":      _parse_float(_attr(attrs, "COVERED_AREA")),
        "semi_covered_sqm": _parse_float(_attr(attrs, "SEMITOTAL_AREA")),
        "rooms":            _parse_int(_attr(attrs, "ROOMS")),
        "bedrooms":         _parse_int(_attr(attrs, "BEDROOMS")),
        "bathrooms":        _parse_int(_attr(attrs, "FULL_BATHROOMS")),
        "toilettes":        _parse_int(_attr(attrs, "TOILET")),
        "garages":          _parse_int(_attr(attrs, "PARKING_LOTS")),
        "floor":            _parse_int(_attr(attrs, "FLOOR")),
        "building_floors":  _parse_int(_attr(attrs, "BUILDING_FLOORS")),
        "age_years":        _parse_int(_attr(attrs, "PROPERTY_AGE")),
        "orientation":      _attr(attrs, "ORIENTATION"),
        "luminosity":       _attr(attrs, "LUMINOSITY"),
        "has_balcony":      _attr(attrs, "HAS_BALCONY") == "Si" or _bool_feature(description, ["balcón", "balcon"]),
        "has_terrace":      _attr(attrs, "HAS_TERRACE") == "Si" or _bool_feature(description, ["terraza"]),
        "has_garden":       _bool_feature(description, ["jardín", "jardin"]),
        "has_pool":         _attr(attrs, "HAS_POOL") == "Si" or _bool_feature(description, ["pileta", "piscina"]),
        "has_gym":          _attr(attrs, "HAS_GYM") == "Si" or _bool_feature(description, ["gimnasio", "gym"]),
        "has_security_24h": _bool_feature(description, ["seguridad 24", "vigilancia"]),
        "has_sum":          _bool_feature(description, ["sum", "salón de usos"]),
        "has_laundry":      _bool_feature(description, ["laundry", "lavadero"]),
        "has_elevator":     _attr(attrs, "HAS_ELEVATOR") == "Si" or _bool_feature(description, ["ascensor"]),
        "has_storage_room": _bool_feature(description, ["baulera", "depósito"]),
        "has_heating":      _bool_feature(description, ["calefacción", "calefaccion"]),
        "has_ac":           _bool_feature(description, ["aire acondicionado", "a/c"]),
        "has_gas":          _bool_feature(description, ["gas natural"]),
        "has_hot_water":    _bool_feature(description, ["agua caliente"]),
        "has_video_tour":   item.get("video_id") is not None,
        "pets_allowed":     _attr(attrs, "ALLOWS_PETS") == "Si",
        "professional_allowed": _bool_feature(description, ["apto profesional"]),
        "bank_allowed":     _bool_feature(description, ["apto banco"]),
        "credit_allowed":   _bool_feature(description, ["apto crédito", "apto credito"]),
        "view_type":        _attr(attrs, "VIEW_TYPE"),
        "position":         _attr(attrs, "PROPERTY_POSITION"),
        "address":          loc.get("address_line") or loc.get("address"),
        "neighborhood":     (loc.get("neighborhood") or {}).get("name"),
        "district":         (loc.get("city") or {}).get("name"),
        "province":         (loc.get("state") or {}).get("name"),
        "latitude":         geo.get("latitude") or loc.get("latitude"),
        "longitude":        geo.get("longitude") or loc.get("longitude"),
        "seller_name":      seller.get("nickname"),
        "seller_type":      "inmobiliaria" if seller.get("real_estate_agency") else "particular",
        "seller_phone":     None,
        "seller_id":        str(seller.get("id", "")),
        "published_at":     pub_date,
        "updated_at":       pub_date,
        "photos_count":     len(images),
        "times_updated":    0,
        "ml_visits":        item.get("visits"),
        "image_urls":       images,
    }

    sale_status, sold_at = _detect_sale_status(item)
    prop["sale_status"] = sale_status
    prop["sold_at"]     = sold_at

    return _computed_fields(prop)


def scrape_mercadolibre() -> int:
    logger.info("Starting MercadoLibre scraper")
    total    = 0
    all_ids: list[str] = []

    with httpx.Client(headers={"User-Agent": "real-estate-scraper/1.0"}) as client:
        for prop_type, category in ML_PROPERTY_TYPES.items():
            logger.info(f"Scraping MercadoLibre: {prop_type}")
            offset = 0

            while True:
                try:
                    result = _search_page(client, category, offset)
                except Exception as e:
                    logger.error(f"Search failed at offset {offset}: {e}")
                    break

                items = result.get("results", [])
                if not items:
                    break

                for summary in items:
                    item_id = summary.get("id")
                    try:
                        item        = _get_item(client, item_id)
                        description = _get_description(client, item_id)
                        prop        = _parse_item(item, prop_type, description)
                    except Exception as e:
                        logger.error(f"Error processing item {item_id}: {e}")
                        continue

                    prop_id = upsert_property(prop)
                    if prop_id:
                        all_ids.append(prop["source_id"])
                        image_urls = prop.pop("image_urls", [])
                        if image_urls:
                            images = download_images(prop_id, "mercadolibre", image_urls)
                            save_images(prop_id, images)
                        total += 1

                    time.sleep(REQUEST_DELAY)

                paging = result.get("paging", {})
                offset += paging.get("limit", 50)
                if offset >= paging.get("total", 0):
                    break

    mark_sold_or_removed("mercadolibre", all_ids)
    logger.info(f"MercadoLibre finished: {total} properties processed")
    return total
