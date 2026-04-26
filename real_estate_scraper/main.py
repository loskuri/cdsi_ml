import os
from loguru import logger
from scrapers.zonaprop import scrape_zonaprop
from scrapers.mercadolibre import scrape_mercadolibre
from enrichment.osm import run_osm_enrichment
from enrichment.georef import run_georef_enrichment
from qa import run_qa
from config import LOGS_DIR

os.makedirs(LOGS_DIR, exist_ok=True)

logger.add(
    os.path.join(LOGS_DIR, "scraper_{time:YYYY-MM-DD}.log"),
    rotation="1 week",
    retention="4 weeks",
    level="INFO",
)


def run():
    logger.info("=" * 60)
    logger.info("Real Estate Scraper - AMBA Argentina")
    logger.info("=" * 60)

    results = {}

    logger.info("Step 1/5: Zonaprop")
    results["zonaprop"] = scrape_zonaprop()

    logger.info("Step 2/5: MercadoLibre")
    results["mercadolibre"] = scrape_mercadolibre()

    logger.info("Step 3/5: Georef enrichment")
    results["georef"] = run_georef_enrichment()

    logger.info("Step 4/5: OSM enrichment")
    results["osm"] = run_osm_enrichment()

    logger.info("Step 5/5: QA")
    results["qa_ok"] = run_qa()

    logger.info("=" * 60)
    logger.info("Run complete:")
    for k, v in results.items():
        logger.info(f"  {k}: {v}")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
