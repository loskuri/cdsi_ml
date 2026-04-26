import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL
DB_HOST     = os.getenv("POSTGRES_HOST", "localhost")
DB_USER     = os.getenv("POSTGRES_USER", "realestate")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "realestate123")
DB_NAME     = os.getenv("POSTGRES_DB", "real_estate")
DB_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))

DB_DSN = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"

# Scheduler
SCHEDULE_DAY  = os.getenv("SCHEDULE_DAY", "sunday")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "2"))

# Paths
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "images")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")

# Scraping
REQUEST_TIMEOUT    = 30
REQUEST_DELAY      = 2       # segundos entre requests
MAX_RETRIES        = 3
PLAYWRIGHT_TIMEOUT = 60_000  # ms

# Zonaprop
ZONAPROP_BASE_URL = "https://www.zonaprop.com.ar"
ZONAPROP_PROPERTY_TYPES = {
    "departamento": "departamentos-venta",
    "casa":         "casas-venta",
    "ph":           "ph-venta",
}

# MercadoLibre
ML_API_BASE        = "https://api.mercadolibre.com"
ML_SITE            = "MLA"
ML_REAL_ESTATE_CAT = "MLA1459"
ML_PROPERTY_TYPES  = {
    "departamento": "MLA1472",
    "casa":         "MLA1473",
    "ph":           "MLA79243",
}

# AMBA - zonas y partidos
AMBA_ZONES = {
    "CABA": [
        "Palermo", "Belgrano", "Recoleta", "San Telmo", "Almagro",
        "Caballito", "Villa Crespo", "Flores", "Balvanera", "Monserrat",
        "Puerto Madero", "Retiro", "Villa Urquiza", "Coghlan", "Saavedra",
        "Nuñez", "Colegiales", "Chacarita", "Villa del Parque", "Devoto",
        "Villa Pueyrredón", "Parque Chacabuco", "Boedo", "San Cristóbal",
        "Barracas", "La Boca", "Nueva Pompeya", "Parque Patricios",
        "Mataderos", "Villa Lugano", "Villa Riachuelo", "Liniers", "Versalles",
        "Monte Castro", "Vélez Sarsfield", "Villa Real", "Floresta",
        "Villa Luro", "Villa General Mitre", "Agronomía", "Parque Chas",
        "Villa Ortúzar", "Paternal", "Villa Santa Rita", "Villa Gral. Mitre",
    ],
    "GBA Norte": [
        "San Isidro", "Vicente López", "San Fernando", "Tigre", "Pilar",
        "Escobar", "Campana", "Zárate", "Exaltación de la Cruz", "San Martín",
        "Tres de Febrero", "Malvinas Argentinas", "José C. Paz",
        "San Miguel", "Moreno",
    ],
    "GBA Oeste": [
        "La Matanza", "Morón", "Ituzaingó", "Hurlingham", "Merlo",
        "Marcos Paz", "General Las Heras", "Luján", "Mercedes",
    ],
    "GBA Sur": [
        "Lomas de Zamora", "Lanús", "Avellaneda", "Quilmes", "Berazategui",
        "Florencio Varela", "Almirante Brown", "Esteban Echeverría",
        "Ezeiza", "San Vicente", "Presidente Perón", "Cañuelas",
    ],
}

# Coordenadas de referencia
OBELISK_LAT = -34.6037
OBELISK_LON = -58.3816
