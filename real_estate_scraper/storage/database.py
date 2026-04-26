import json
import psycopg2
import psycopg2.extras
from datetime import date, datetime
from loguru import logger
from config import DB_DSN


def get_connection():
    return psycopg2.connect(DB_DSN)


def upsert_property(prop: dict) -> int | None:
    """
    Inserta o actualiza una propiedad. Retorna el id interno.
    Maneja automáticamente price_history JSONB sin duplicar fechas.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # Buscar si ya existe
                cur.execute(
                    "SELECT id, price, currency, price_history, original_price, price_change_count FROM properties WHERE source = %s AND source_id = %s",
                    (prop.get("source"), prop.get("source_id")),
                )
                existing = cur.fetchone()

                if existing:
                    prop_id = existing["id"]
                    _update_property(cur, prop, existing)
                else:
                    prop_id = _insert_property(cur, prop)

                conn.commit()
                return prop_id

    except Exception as e:
        logger.error(f"Error upserting property {prop.get('source_id')}: {e}")
        return None


def _insert_property(cur, prop: dict) -> int:
    today = date.today().isoformat()
    initial_history = []
    if prop.get("price"):
        initial_history = [{"date": today, "price": float(prop["price"]), "currency": prop.get("currency", "USD")}]

    fields = _defaults(prop)
    fields.update({
        "price_history":      json.dumps(initial_history),
        "original_price":     prop.get("price"),
        "price_change_count": 0,
        "last_price_change_at": None,
        "price_change_pct":   None,
        "sale_status":        prop.get("sale_status", "active"),
        "sold_at":            prop.get("sold_at"),
        "ml_visits":          prop.get("ml_visits"),
    })

    sql = """
        INSERT INTO properties (
            source, source_id, url, title, description, property_type,
            operation_type, status,
            price, currency, expenses, expenses_currency,
            price_per_sqm_covered, price_per_sqm_total, price_per_room,
            total_sqm, covered_sqm, semi_covered_sqm, ratio_covered_total,
            rooms, bedrooms, bathrooms, toilettes, garages,
            floor, building_floors, age_years, orientation, luminosity,
            has_balcony, has_terrace, has_garden, has_pool, has_gym,
            has_security_24h, has_sum, has_laundry, has_elevator,
            has_storage_room, has_heating, has_ac, has_gas, has_hot_water,
            has_video_tour, pets_allowed, professional_allowed, bank_allowed, credit_allowed,
            view_type, position,
            address, neighborhood, normalized_neighborhood, district,
            province, amba_zone, latitude, longitude,
            distance_to_subway_m, nearest_subway_station,
            distance_to_train_m, nearest_train_station,
            distance_to_park_m, nearest_park, distance_to_obelisk_m,
            seller_name, seller_type, seller_phone, seller_id,
            price_history, original_price, price_change_count,
            last_price_change_at, price_change_pct,
            sale_status, sold_at, ml_visits,
            published_at, updated_at, days_on_market,
            photos_count, times_updated, listing_quality_score,
            scraped_at, last_scraped_at, is_active
        ) VALUES (
            %(source)s, %(source_id)s, %(url)s, %(title)s, %(description)s,
            %(property_type)s, %(operation_type)s, %(status)s,
            %(price)s, %(currency)s, %(expenses)s, %(expenses_currency)s,
            %(price_per_sqm_covered)s, %(price_per_sqm_total)s, %(price_per_room)s,
            %(total_sqm)s, %(covered_sqm)s, %(semi_covered_sqm)s, %(ratio_covered_total)s,
            %(rooms)s, %(bedrooms)s, %(bathrooms)s, %(toilettes)s, %(garages)s,
            %(floor)s, %(building_floors)s, %(age_years)s, %(orientation)s, %(luminosity)s,
            %(has_balcony)s, %(has_terrace)s, %(has_garden)s, %(has_pool)s, %(has_gym)s,
            %(has_security_24h)s, %(has_sum)s, %(has_laundry)s, %(has_elevator)s,
            %(has_storage_room)s, %(has_heating)s, %(has_ac)s, %(has_gas)s, %(has_hot_water)s,
            %(has_video_tour)s, %(pets_allowed)s, %(professional_allowed)s,
            %(bank_allowed)s, %(credit_allowed)s,
            %(view_type)s, %(position)s,
            %(address)s, %(neighborhood)s, %(normalized_neighborhood)s, %(district)s,
            %(province)s, %(amba_zone)s, %(latitude)s, %(longitude)s,
            %(distance_to_subway_m)s, %(nearest_subway_station)s,
            %(distance_to_train_m)s, %(nearest_train_station)s,
            %(distance_to_park_m)s, %(nearest_park)s, %(distance_to_obelisk_m)s,
            %(seller_name)s, %(seller_type)s, %(seller_phone)s, %(seller_id)s,
            %(price_history)s, %(original_price)s, %(price_change_count)s,
            %(last_price_change_at)s, %(price_change_pct)s,
            %(sale_status)s, %(sold_at)s, %(ml_visits)s,
            %(published_at)s, %(updated_at)s, %(days_on_market)s,
            %(photos_count)s, %(times_updated)s, %(listing_quality_score)s,
            NOW(), NOW(), TRUE
        ) RETURNING id
    """
    cur.execute(sql, fields)
    return cur.fetchone()["id"]


def _update_property(cur, prop: dict, existing: dict):
    today       = date.today().isoformat()
    new_price   = prop.get("price")
    old_price   = float(existing["price"]) if existing["price"] else None
    history     = existing["price_history"] or []
    change_count = existing["price_change_count"] or 0
    orig_price  = float(existing["original_price"]) if existing["original_price"] else new_price

    # Actualizar price_history solo si el precio cambió y la fecha no existe ya
    last_price_change_at = None
    if new_price and new_price != old_price:
        existing_dates = {e["date"] for e in history}
        if today not in existing_dates:
            history.append({
                "date":     today,
                "price":    float(new_price),
                "currency": prop.get("currency", "USD"),
            })
            change_count += 1
            last_price_change_at = today

    price_change_pct = None
    if orig_price and new_price and orig_price != 0:
        price_change_pct = round((new_price - orig_price) / orig_price * 100, 2)

    sale_status = prop.get("sale_status", "active")
    sold_at     = prop.get("sold_at") if sale_status == "sold" else None

    cur.execute("""
        UPDATE properties SET
            url                   = %(url)s,
            title                 = %(title)s,
            description           = %(description)s,
            status                = %(status)s,
            price                 = %(price)s,
            currency              = %(currency)s,
            expenses              = %(expenses)s,
            price_per_sqm_covered = %(price_per_sqm_covered)s,
            price_per_sqm_total   = %(price_per_sqm_total)s,
            price_per_room        = %(price_per_room)s,
            price_history         = %(price_history)s,
            price_change_count    = %(price_change_count)s,
            last_price_change_at  = COALESCE(%(last_price_change_at)s, last_price_change_at),
            price_change_pct      = %(price_change_pct)s,
            sale_status           = %(sale_status)s,
            sold_at               = COALESCE(%(sold_at)s, sold_at),
            ml_visits             = COALESCE(%(ml_visits)s, ml_visits),
            days_on_market        = %(days_on_market)s,
            photos_count          = %(photos_count)s,
            times_updated         = times_updated + 1,
            listing_quality_score = %(listing_quality_score)s,
            last_scraped_at       = NOW(),
            is_active             = %(is_active)s
        WHERE id = %(id)s
    """, {
        "id":                   existing["id"],
        "url":                  prop.get("url"),
        "title":                prop.get("title"),
        "description":          prop.get("description"),
        "status":               prop.get("status"),
        "price":                new_price,
        "currency":             prop.get("currency"),
        "expenses":             prop.get("expenses"),
        "price_per_sqm_covered": prop.get("price_per_sqm_covered"),
        "price_per_sqm_total":  prop.get("price_per_sqm_total"),
        "price_per_room":       prop.get("price_per_room"),
        "price_history":        json.dumps(history),
        "price_change_count":   change_count,
        "last_price_change_at": last_price_change_at,
        "price_change_pct":     price_change_pct,
        "sale_status":          sale_status,
        "sold_at":              sold_at,
        "ml_visits":            prop.get("ml_visits"),
        "days_on_market":       prop.get("days_on_market"),
        "photos_count":         prop.get("photos_count"),
        "listing_quality_score": prop.get("listing_quality_score"),
        "is_active":            sale_status == "active",
    })


def save_images(property_id: int, images: list[dict]):
    sql = """
        INSERT INTO property_images (property_id, url, local_path, image_order)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (property_id, url) DO NOTHING
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for img in images:
                    cur.execute(sql, (
                        property_id,
                        img.get("url"),
                        img.get("local_path"),
                        img.get("order"),
                    ))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving images for property {property_id}: {e}")


def mark_sold_or_removed(source: str, active_ids: list[str]):
    """
    Propiedades que ya no aparecen en el sitio:
    - Si estaban 'active' → pasan a 'removed'
    - El scraper individual puede marcarlas como 'sold' cuando detecta la señal explícita
    """
    if not active_ids:
        return
    sql = """
        UPDATE properties
        SET sale_status     = 'removed',
            is_active       = FALSE,
            last_scraped_at = NOW()
        WHERE source      = %s
          AND source_id   != ALL(%s)
          AND sale_status  = 'active'
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source, active_ids))
            conn.commit()
    except Exception as e:
        logger.error(f"Error marking removed for {source}: {e}")


def _defaults(prop: dict) -> dict:
    fields = [
        "source", "source_id", "url", "title", "description", "property_type",
        "operation_type", "status", "price", "currency", "expenses", "expenses_currency",
        "price_per_sqm_covered", "price_per_sqm_total", "price_per_room",
        "total_sqm", "covered_sqm", "semi_covered_sqm", "ratio_covered_total",
        "rooms", "bedrooms", "bathrooms", "toilettes", "garages",
        "floor", "building_floors", "age_years", "orientation", "luminosity",
        "has_balcony", "has_terrace", "has_garden", "has_pool", "has_gym",
        "has_security_24h", "has_sum", "has_laundry", "has_elevator",
        "has_storage_room", "has_heating", "has_ac", "has_gas", "has_hot_water",
        "has_video_tour", "pets_allowed", "professional_allowed", "bank_allowed",
        "credit_allowed", "view_type", "position", "address", "neighborhood",
        "normalized_neighborhood", "district", "province", "amba_zone",
        "latitude", "longitude", "distance_to_subway_m", "nearest_subway_station",
        "distance_to_train_m", "nearest_train_station", "distance_to_park_m",
        "nearest_park", "distance_to_obelisk_m", "seller_name", "seller_type",
        "seller_phone", "seller_id", "published_at", "updated_at",
        "days_on_market", "photos_count", "times_updated", "listing_quality_score",
    ]
    return {f: prop.get(f) for f in fields}
