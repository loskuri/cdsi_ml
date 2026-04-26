import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
import psycopg2
from config import DB_DSN, AMBA_ZONES


GEOREF_API = "https://apis.datos.gob.ar/georef/api"


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
def _normalize_neighborhood(neighborhood: str, province: str = "Buenos Aires") -> str | None:
    """
    Usa la API Georef del gobierno argentino para normalizar el nombre del barrio.
    """
    try:
        resp = httpx.get(
            f"{GEOREF_API}/localidades",
            params={"nombre": neighborhood, "provincia": province, "max": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("localidades", [])
        if results:
            return results[0].get("nombre")

        # Fallback: buscar en barrios (CABA)
        resp2 = httpx.get(
            f"{GEOREF_API}/localidades",
            params={"nombre": neighborhood, "provincia": "Ciudad Autónoma de Buenos Aires", "max": 1},
            timeout=10,
        )
        resp2.raise_for_status()
        data2 = resp2.json()
        results2 = data2.get("localidades", [])
        if results2:
            return results2[0].get("nombre")

        return None
    except Exception as e:
        logger.warning(f"Georef failed for '{neighborhood}': {e}")
        return None


def _infer_amba_zone(district: str, province: str, neighborhood: str) -> str | None:
    """Infiere la zona AMBA basándose en partido/barrio."""
    if province and "Ciudad Autónoma" in province:
        return "CABA"

    target = (district or neighborhood or "").lower()
    for zone, places in AMBA_ZONES.items():
        for place in places:
            if place.lower() in target:
                return zone
    return None


def run_georef_enrichment():
    """Normaliza barrios y asigna zona AMBA para propiedades sin ese dato."""
    logger.info("Starting Georef enrichment")
    count = 0

    sql_select = """
        SELECT id, neighborhood, district, province FROM properties
        WHERE neighborhood IS NOT NULL
          AND normalized_neighborhood IS NULL
        LIMIT 1000
    """
    sql_update = """
        UPDATE properties SET
            normalized_neighborhood = %(normalized_neighborhood)s,
            amba_zone               = %(amba_zone)s
        WHERE id = %(id)s
    """

    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_select)
            rows = cur.fetchall()

        for prop_id, neighborhood, district, province in rows:
            normalized = _normalize_neighborhood(neighborhood, province or "Buenos Aires")
            amba_zone  = _infer_amba_zone(district, province or "", neighborhood)

            with conn.cursor() as cur:
                cur.execute(sql_update, {
                    "id":                       prop_id,
                    "normalized_neighborhood":  normalized or neighborhood,
                    "amba_zone":                amba_zone,
                })
            conn.commit()
            count += 1

    logger.info(f"Georef enrichment done: {count} properties updated")
    return count
