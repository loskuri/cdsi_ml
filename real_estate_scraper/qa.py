"""
QA - Validación de calidad de datos post-scraping.
Corre automáticamente al final de cada ejecución o manualmente:
    docker-compose exec scraper python qa.py
"""

import json
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from loguru import logger
from config import DB_DSN, LOGS_DIR
import os

os.makedirs(LOGS_DIR, exist_ok=True)
logger.add(os.path.join(LOGS_DIR, "qa_{time:YYYY-MM-DD}.log"), rotation="1 week", retention="4 weeks")

THRESHOLDS = {
    "min_total_properties":       100,
    "min_new_this_run":           50,
    "max_missing_price_pct":      10.0,
    "max_missing_location_pct":   15.0,
    "max_missing_sqm_pct":        20.0,
    "max_duplicate_urls_pct":     1.0,
    "min_images_per_property":    1.0,
    "max_price_outlier_usd":      5_000_000,
    "min_price_usd":              10_000,
    "max_sqm":                    2_000,
    "min_sqm":                    10,
}


def check_total_volume(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM properties WHERE is_active = TRUE")
    total = cur.fetchone()[0]
    ok = total >= THRESHOLDS["min_total_properties"]
    return {"check": "Volumen total de propiedades activas", "value": total, "threshold": f">= {THRESHOLDS['min_total_properties']}", "ok": ok}


def check_recent_activity(cur) -> dict:
    since = date.today() - timedelta(hours=24)
    cur.execute("SELECT COUNT(*) FROM properties WHERE last_scraped_at >= %s", (since,))
    recent = cur.fetchone()[0]
    ok = recent >= THRESHOLDS["min_new_this_run"]
    return {"check": "Propiedades actualizadas en las últimas 24h", "value": recent, "threshold": f">= {THRESHOLDS['min_new_this_run']}", "ok": ok}


def check_missing_price(cur) -> dict:
    cur.execute("SELECT COUNT(*) FILTER (WHERE price IS NULL) AS missing, COUNT(*) AS total FROM properties WHERE is_active = TRUE")
    row = cur.fetchone()
    pct = round(row[0] / row[1] * 100, 2) if row[1] else 0
    ok  = pct <= THRESHOLDS["max_missing_price_pct"]
    return {"check": "Propiedades sin precio", "value": f"{row[0]} ({pct}%)", "threshold": f"<= {THRESHOLDS['max_missing_price_pct']}%", "ok": ok}


def check_missing_location(cur) -> dict:
    cur.execute("SELECT COUNT(*) FILTER (WHERE latitude IS NULL OR longitude IS NULL) AS missing, COUNT(*) AS total FROM properties WHERE is_active = TRUE")
    row = cur.fetchone()
    pct = round(row[0] / row[1] * 100, 2) if row[1] else 0
    ok  = pct <= THRESHOLDS["max_missing_location_pct"]
    return {"check": "Propiedades sin coordenadas", "value": f"{row[0]} ({pct}%)", "threshold": f"<= {THRESHOLDS['max_missing_location_pct']}%", "ok": ok}


def check_missing_sqm(cur) -> dict:
    cur.execute("SELECT COUNT(*) FILTER (WHERE total_sqm IS NULL AND covered_sqm IS NULL) AS missing, COUNT(*) AS total FROM properties WHERE is_active = TRUE")
    row = cur.fetchone()
    pct = round(row[0] / row[1] * 100, 2) if row[1] else 0
    ok  = pct <= THRESHOLDS["max_missing_sqm_pct"]
    return {"check": "Propiedades sin superficie", "value": f"{row[0]} ({pct}%)", "threshold": f"<= {THRESHOLDS['max_missing_sqm_pct']}%", "ok": ok}


def check_duplicate_urls(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM (SELECT url, COUNT(*) FROM properties GROUP BY url HAVING COUNT(*) > 1) dups")
    dups = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM properties")
    total = cur.fetchone()[0]
    pct = round(dups / total * 100, 2) if total else 0
    ok  = pct <= THRESHOLDS["max_duplicate_urls_pct"]
    return {"check": "URLs duplicadas", "value": f"{dups} ({pct}%)", "threshold": f"<= {THRESHOLDS['max_duplicate_urls_pct']}%", "ok": ok}


def check_price_outliers(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM properties WHERE is_active = TRUE AND currency = 'USD' AND (price > %(max)s OR price < %(min)s)", {"max": THRESHOLDS["max_price_outlier_usd"], "min": THRESHOLDS["min_price_usd"]})
    outliers = cur.fetchone()[0]
    ok = outliers == 0
    return {"check": "Precios USD fuera de rango razonable", "value": outliers, "threshold": f"0 (rango: ${THRESHOLDS['min_price_usd']:,} - ${THRESHOLDS['max_price_outlier_usd']:,})", "ok": ok}


def check_sqm_outliers(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM properties WHERE is_active = TRUE AND ((total_sqm IS NOT NULL AND (total_sqm > %(max)s OR total_sqm < %(min)s)) OR (covered_sqm IS NOT NULL AND covered_sqm > total_sqm))", {"max": THRESHOLDS["max_sqm"], "min": THRESHOLDS["min_sqm"]})
    outliers = cur.fetchone()[0]
    ok = outliers == 0
    return {"check": "Superficies fuera de rango o cubierta > total", "value": outliers, "threshold": f"0 (rango: {THRESHOLDS['min_sqm']} - {THRESHOLDS['max_sqm']} m²)", "ok": ok}


def check_images_coverage(cur) -> dict:
    cur.execute("SELECT COUNT(DISTINCT pi.property_id) AS props_with_images, COUNT(pi.id) AS total_images, COUNT(DISTINCT p.id) AS total_props FROM properties p LEFT JOIN property_images pi ON pi.property_id = p.id WHERE p.is_active = TRUE")
    row = cur.fetchone()
    props_with = row[0]
    total_imgs = row[1]
    total_props = row[2]
    avg = round(total_imgs / total_props, 2) if total_props else 0
    ok  = avg >= THRESHOLDS["min_images_per_property"]
    return {"check": "Cobertura de imágenes", "value": f"{props_with}/{total_props} propiedades con imágenes, promedio {avg} img/prop", "threshold": f">= {THRESHOLDS['min_images_per_property']} img/prop promedio", "ok": ok}


def check_price_history_integrity(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM properties WHERE is_active = TRUE AND price IS NOT NULL AND (price_history IS NULL OR price_history = '[]'::jsonb)")
    broken = cur.fetchone()[0]
    ok = broken == 0
    return {"check": "Propiedades con precio pero sin price_history", "value": broken, "threshold": "0", "ok": ok}


def check_sale_status_consistency(cur) -> dict:
    cur.execute("SELECT COUNT(*) FROM properties WHERE (sale_status = 'active' AND is_active = FALSE) OR (sale_status IN ('sold', 'removed') AND is_active = TRUE)")
    inconsistent = cur.fetchone()[0]
    ok = inconsistent == 0
    return {"check": "Consistencia sale_status vs is_active", "value": inconsistent, "threshold": "0", "ok": ok}


def check_by_source(cur) -> dict:
    cur.execute("SELECT source, COUNT(*) FILTER (WHERE is_active = TRUE) AS activas, COUNT(*) FILTER (WHERE sale_status = 'sold') AS vendidas, COUNT(*) FILTER (WHERE sale_status = 'removed') AS removidas, ROUND(AVG(price) FILTER (WHERE currency = 'USD' AND is_active = TRUE)) AS avg_price_usd, COUNT(*) FILTER (WHERE price IS NULL AND is_active = TRUE) AS sin_precio FROM properties GROUP BY source ORDER BY source")
    rows = cur.fetchall()
    detail = [{"source": r[0], "activas": r[1], "vendidas": r[2], "removidas": r[3], "avg_price_usd": r[4], "sin_precio": r[5]} for r in rows]
    return {"check": "Resumen por fuente", "value": detail, "ok": True}


def check_enrichment_coverage(cur) -> dict:
    cur.execute("SELECT COUNT(*) FILTER (WHERE latitude IS NOT NULL) AS con_coords, COUNT(*) FILTER (WHERE distance_to_subway_m IS NOT NULL) AS con_subte, COUNT(*) FILTER (WHERE normalized_neighborhood IS NOT NULL) AS con_barrio, COUNT(*) FILTER (WHERE amba_zone IS NOT NULL) AS con_zona, COUNT(*) AS total FROM properties WHERE is_active = TRUE")
    r = cur.fetchone()
    total = r[4] or 1
    return {"check": "Cobertura de enriquecimiento geoespacial", "value": {"con_coords": f"{r[0]}/{total} ({round(r[0]/total*100)}%)", "con_subte": f"{r[1]}/{total} ({round(r[1]/total*100)}%)", "con_barrio": f"{r[2]}/{total} ({round(r[2]/total*100)}%)", "con_zona": f"{r[3]}/{total} ({round(r[3]/total*100)}%)"}, "ok": True}


CHECKS = [check_total_volume, check_recent_activity, check_missing_price, check_missing_location, check_missing_sqm, check_duplicate_urls, check_price_outliers, check_sqm_outliers, check_images_coverage, check_price_history_integrity, check_sale_status_consistency, check_by_source, check_enrichment_coverage]


def run_qa() -> bool:
    logger.info("=" * 60)
    logger.info("QA - Validación de datos")
    logger.info("=" * 60)

    passed = 0
    failed = 0
    warnings = []

    with psycopg2.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for check_fn in CHECKS:
                result = check_fn(cur)
                status = "✓" if result["ok"] else "✗"

                if isinstance(result["value"], (list, dict)):
                    logger.info(f"{status} {result['check']}:")
                    logger.info(f"   {json.dumps(result['value'], ensure_ascii=False, indent=4)}")
                else:
                    threshold_str = f"  (umbral: {result.get('threshold', '-')})" if not result["ok"] else ""
                    logger.info(f"{status} {result['check']}: {result['value']}{threshold_str}")

                if result["ok"]:
                    passed += 1
                else:
                    failed += 1
                    warnings.append(result["check"])

    logger.info("=" * 60)
    logger.info(f"Resultado: {passed} OK  |  {failed} ALERTAS")
    if warnings:
        logger.warning("Checks con alerta:")
        for w in warnings:
            logger.warning(f"  - {w}")
    logger.info("=" * 60)

    return failed == 0


if __name__ == "__main__":
    all_ok = run_qa()
    exit(0 if all_ok else 1)
