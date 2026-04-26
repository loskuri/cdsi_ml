import re
import time
import json
from datetime import datetime, date
from math import radians, cos, sin, asin, sqrt
from loguru import logger
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tenacity import retry, stop_after_attempt, wait_fixed

from config import (
    ZONAPROP_BASE_URL, ZONAPROP_PROPERTY_TYPES,
    PLAYWRIGHT_TIMEOUT, REQUEST_DELAY, OBELISK_LAT, OBELISK_LON,
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
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


def _calculate_quality_score(prop: dict) -> float:
    score = 0
    if prop.get("price"):           score += 20
    if prop.get("total_sqm"):       score += 15
    if prop.get("covered_sqm"):     score += 10
    if prop.get("rooms"):           score += 10
    if prop.get("latitude"):        score += 15
    if prop.get("description"):     score += 10
    photos = prop.get("photos_count") or 0
    score += min(photos * 2, 20)
    return round(score, 2)


def _computed_fields(prop: dict) -> dict:
    price  = prop.get("price")
    cov    = prop.get("covered_sqm")
    total  = prop.get("total_sqm")
    rooms  = prop.get("rooms")
    lat    = prop.get("latitude")
    lon    = prop.get("longitude")

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


def _extract_listing_urls(page) -> list[str]:
    return page.eval_on_selector_all(
        "a[data-qa='posting PROPERTY']",
        "els => els.map(e => e.href)"
    )


def _detect_sale_status(page) -> tuple[str, datetime | None]:
    try:
        body = page.inner_text("body").lower()
        url  = page.url.lower()
        if any(k in body for k in ["esta propiedad fue vendida", "inmueble vendido", "ya fue vendido"]):
            return "sold", datetime.now()
        if "vendido" in url:
            return "sold", datetime.now()
    except Exception:
        pass
    return "active", None


def _extract_detail(page, url: str, prop_type: str) -> dict | None:
    try:
        response = page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if response and response.status in (404, 410):
            return {"_removed": True, "url": url}

        sale_status, sold_at = _detect_sale_status(page)

        raw = page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }
        """)

        if raw:
            data = json.loads(raw)
            prop = _parse_next_data(data, url, prop_type)
        else:
            prop = _parse_dom(page, url, prop_type)

        if prop:
            prop["sale_status"] = sale_status
            prop["sold_at"]     = sold_at

        return prop

    except PWTimeout:
        logger.warning(f"Timeout on {url}")
        return None
    except Exception as e:
        logger.error(f"Error extracting {url}: {e}")
        return None


def _parse_next_data(data: dict, url: str, prop_type: str) -> dict:
    try:
        props = data["props"]["pageProps"]
        listing = props.get("listing") or props.get("real_estate") or {}
        geo     = listing.get("geo", {})
        features = {f["id"]: f.get("value_name") for f in listing.get("attributes", [])}
        desc_raw  = listing.get("description", {})
        desc_text = desc_raw.get("plain_text", "") if isinstance(desc_raw, dict) else str(desc_raw)
        price_data = listing.get("price_details", {}) or listing.get("price", {})
        currency   = price_data.get("currency_id", "USD")
        price      = _parse_float(price_data.get("amount") or price_data.get("price"))
        expenses   = _parse_float(listing.get("expenses", {}).get("amount") if isinstance(listing.get("expenses"), dict) else listing.get("expenses"))

        images = [i.get("url") or i.get("link") for i in listing.get("pictures", []) if i.get("url") or i.get("link")]

        seller_info = listing.get("seller", {}) or {}
        seller_type = "inmobiliaria" if seller_info.get("real_estate_agency") else "particular"

        pub_date = listing.get("start_time") or listing.get("date_created")
        if pub_date:
            try:
                pub_date = datetime.fromisoformat(pub_date[:19])
            except Exception:
                pub_date = None

        prop = {
            "source":           "zonaprop",
            "source_id":        str(listing.get("id", url.split("-")[-1].replace(".html", ""))),
            "url":              url,
            "title":            listing.get("title", ""),
            "description":      desc_text,
            "property_type":    prop_type,
            "operation_type":   "venta",
            "status":           features.get("PROPERTY_CONDITION"),
            "price":            price,
            "currency":         currency,
            "expenses":         expenses,
            "expenses_currency": currency,
            "total_sqm":        _parse_float(features.get("TOTAL_AREA")),
            "covered_sqm":      _parse_float(features.get("COVERED_AREA")),
            "semi_covered_sqm": _parse_float(features.get("SEMITOTAL_AREA")),
            "rooms":            _parse_int(features.get("ROOMS")),
            "bedrooms":         _parse_int(features.get("BEDROOMS")),
            "bathrooms":        _parse_int(features.get("FULL_BATHROOMS")),
            "toilettes":        _parse_int(features.get("TOILET")),
            "garages":          _parse_int(features.get("PARKING_LOTS")),
            "floor":            _parse_int(features.get("FLOOR")),
            "building_floors":  _parse_int(features.get("BUILDING_FLOORS")),
            "age_years":        _parse_int(features.get("PROPERTY_AGE")),
            "orientation":      features.get("ORIENTATION"),
            "luminosity":       features.get("LUMINOSITY"),
            "has_balcony":      _bool_feature(desc_text, ["balcón", "balcon"]),
            "has_terrace":      _bool_feature(desc_text, ["terraza"]),
            "has_garden":       _bool_feature(desc_text, ["jardín", "jardin"]),
            "has_pool":         features.get("HAS_POOL") == "true" or _bool_feature(desc_text, ["pileta", "piscina"]),
            "has_gym":          features.get("HAS_GYM") == "true" or _bool_feature(desc_text, ["gimnasio", "gym"]),
            "has_security_24h": _bool_feature(desc_text, ["seguridad 24", "vigilancia"]),
            "has_sum":          _bool_feature(desc_text, ["sum", "salón de usos"]),
            "has_laundry":      _bool_feature(desc_text, ["laundry", "lavadero"]),
            "has_elevator":     features.get("HAS_ELEVATOR") == "true" or _bool_feature(desc_text, ["ascensor"]),
            "has_storage_room": _bool_feature(desc_text, ["baulera", "depósito"]),
            "has_heating":      _bool_feature(desc_text, ["calefacción", "calefaccion"]),
            "has_ac":           _bool_feature(desc_text, ["aire acondicionado", "a/c"]),
            "has_gas":          _bool_feature(desc_text, ["gas natural"]),
            "has_hot_water":    _bool_feature(desc_text, ["agua caliente"]),
            "has_video_tour":   bool(listing.get("video")),
            "pets_allowed":     features.get("ALLOWS_PETS") == "true",
            "professional_allowed": _bool_feature(desc_text, ["apto profesional"]),
            "bank_allowed":     _bool_feature(desc_text, ["apto banco"]),
            "credit_allowed":   _bool_feature(desc_text, ["apto crédito", "apto credito"]),
            "view_type":        features.get("VIEW_TYPE"),
            "position":         features.get("PROPERTY_POSITION"),
            "address":          listing.get("location", {}).get("address_line"),
            "neighborhood":     listing.get("location", {}).get("neighborhood", {}).get("name"),
            "district":         listing.get("location", {}).get("city", {}).get("name"),
            "province":         listing.get("location", {}).get("state", {}).get("name"),
            "latitude":         geo.get("lat") or listing.get("location", {}).get("lat"),
            "longitude":        geo.get("lon") or listing.get("location", {}).get("lon"),
            "seller_name":      seller_info.get("name"),
            "seller_type":      seller_type,
            "seller_phone":     None,
            "seller_id":        str(seller_info.get("id", "")),
            "published_at":     pub_date,
            "updated_at":       pub_date,
            "photos_count":     len(images),
            "times_updated":    0,
            "image_urls":       images,
        }
        return _computed_fields(prop)
    except Exception as e:
        logger.error(f"Error parsing next_data for {url}: {e}")
        return None


def _parse_dom(page, url: str, prop_type: str) -> dict:
    text = page.inner_text("body")

    price_match = re.search(r"(USD|ARS|u\$s|\$)\s*([\d.,]+)", text)
    price    = _parse_float(price_match.group(2)) if price_match else None
    currency = "USD" if price_match and price_match.group(1) in ("USD", "u$s") else "ARS"

    images = page.eval_on_selector_all(
        "img[src*='zonaprop'], img[data-src*='zonaprop']",
        "els => els.map(e => e.src || e.dataset.src)"
    )

    prop = {
        "source":        "zonaprop",
        "source_id":     url.split("-")[-1].replace(".html", ""),
        "url":           url,
        "property_type": prop_type,
        "operation_type": "venta",
        "price":         price,
        "currency":      currency,
        "title":         page.title(),
        "description":   text[:5000],
        "photos_count":  len(images),
        "image_urls":    images,
    }
    return _computed_fields(prop)


def scrape_zonaprop() -> int:
    logger.info("Starting Zonaprop scraper")
    total = 0
    all_ids: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for prop_type, slug in ZONAPROP_PROPERTY_TYPES.items():
            logger.info(f"Scraping Zonaprop: {prop_type}")
            page_num = 1

            while True:
                list_url = f"{ZONAPROP_BASE_URL}/{slug}-pagina-{page_num}.html"
                try:
                    page.goto(list_url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                except PWTimeout:
                    logger.warning(f"Timeout on list page {list_url}")
                    break

                urls = _extract_listing_urls(page)
                if not urls:
                    logger.info(f"No more listings at page {page_num} for {prop_type}")
                    break

                for detail_url in urls:
                    if not detail_url.startswith("http"):
                        detail_url = ZONAPROP_BASE_URL + detail_url

                    prop = _extract_detail(page, detail_url, prop_type)
                    if not prop:
                        continue

                    if prop.get("_removed"):
                        continue

                    prop_id = upsert_property(prop)
                    if prop_id:
                        all_ids.append(prop.get("source_id"))
                        if prop.get("sale_status") == "active":
                            image_urls = prop.pop("image_urls", [])
                            if image_urls:
                                imgs = download_images(prop_id, "zonaprop", image_urls)
                                save_images(prop_id, imgs)
                        total += 1

                    time.sleep(REQUEST_DELAY)

                page_num += 1

        browser.close()

    mark_sold_or_removed("zonaprop", all_ids)
    logger.info(f"Zonaprop finished: {total} properties processed")
    return total
