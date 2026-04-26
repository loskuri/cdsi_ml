import os
import time
import requests
from pathlib import Path
from loguru import logger
from config import IMAGES_DIR, REQUEST_DELAY


def download_images(property_id: int, source: str, image_urls: list[str]) -> list[dict]:
    """
    Descarga imágenes de una propiedad al disco.
    Retorna lista de dicts con url y local_path para guardar en DB.
    """
    folder = Path(IMAGES_DIR) / f"{source}_{property_id}"
    folder.mkdir(parents=True, exist_ok=True)

    results = []
    for i, url in enumerate(image_urls, start=1):
        local_path = folder / f"{i}.jpg"

        if local_path.exists():
            results.append({"url": url, "local_path": str(local_path), "order": i})
            continue

        try:
            response = requests.get(url, timeout=15, stream=True)
            response.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            results.append({"url": url, "local_path": str(local_path), "order": i})
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")

    return results
