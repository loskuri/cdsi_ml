import overpy
from math import radians, cos, sin, asin, sqrt
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
import psycopg2
from config import DB_DSN


def _haversine_m(lat1, lon1, lat2, lon2) -> int:
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return int(2 * R * asin(sqrt(a)))


@retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
def _query_overpass(query: str):
    api = overpy.Overpass()
    return api.query(query)


def _nearest(lat: float, lon: float, tag_filter: str, radius: int = 2000):
    """
    Busca el elemento OSM más cercano dentro de `radius` metros.
    Retorna (distancia_m, nombre) o (None, None).
    """
    query = f"""
    [out:json][timeout:25];
    (
      node{tag_filter}(around:{radius},{lat},{lon});
      way{tag_filter}(around:{radius},{lat},{lon});
    );
    out center tags;
    """
    try:
        result = _query_overpass(query)
        elements = list(result.nodes) + [w for w in result.ways]
        if not elements:
            return None, None

        best_dist = float("inf")
        best_name = None
        for el in elements:
            elat = el.lat if hasattr(el, "lat") else el.center_lat
            elon = el.lon if hasattr(el, "lon") else el.center_lon
            if elat is None or elon is None:
                continue
            d = _haversine_m(lat, lon, float(elat), float(elon))
            if d < best_dist:
                best_dist = d
                best_name = el.tags.get("name", "")

        return (best_dist if best_dist < float("inf") else None), best_name
    except Exception as e:
        logger.warning(f"OSM query failed ({tag_filter}): {e}")
        return None, None


def enrich_osm(lat: float, lon: float) -> dict:
    dist_subway, name_subway = _nearest(lat, lon, '["station"="subway"]')
    dist_train,  name_train  = _nearest(lat, lon, '["railway"="station"]')
    dist_park,   name_park   = _nearest(lat, lon, '["leisure"~"park|garden"]', radius=1000)

    return {
        "distance_to_subway_m":   dist_subway,
        "nearest_subway_station": name_subway,
        "distance_to_train_m":    dist_train,
        "nearest_train_station":  name_train,
        "distance_to_park_m":     dist_park,
        "nearest_park":           name_park,
    }


def run_osm_enrichment():
    """Enriquece todas las propiedades con coordenadas que aún no tienen datos OSM."""
    logger.info("Starting OSM enrichment")
    count = 0

    sql_select = """
        SELECT id, latitude, longitude FROM properties
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND distance_to_subway_m IS NULL
        LIMIT 500
    """
    sql_update = """
        UPDATE properties SET
            distance_to_subway_m   = %(distance_to_subway_m)s,
            nearest_subway_station = %(nearest_subway_station)s,
            distance_to_train_m    = %(distance_to_train_m)s,
            nearest_train_station  = %(nearest_train_station)s,
            distance_to_park_m     = %(distance_to_park_m)s,
            nearest_park           = %(nearest_park)s
        WHERE id = %(id)s
    """

    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_select)
            rows = cur.fetchall()

        for prop_id, lat, lon in rows:
            enriched = enrich_osm(float(lat), float(lon))
            enriched["id"] = prop_id
            with conn.cursor() as cur:
                cur.execute(sql_update, enriched)
            conn.commit()
            count += 1

    logger.info(f"OSM enrichment done: {count} properties updated")
    return count
