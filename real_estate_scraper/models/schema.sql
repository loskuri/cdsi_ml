-- ============================================================
-- REAL ESTATE SCRAPER - PostgreSQL Schema
-- Zonaprop + MercadoLibre | AMBA Argentina
-- ============================================================

CREATE TABLE IF NOT EXISTS properties (

    -- Identificación
    id                          SERIAL PRIMARY KEY,
    source                      VARCHAR(20) NOT NULL,       -- 'zonaprop' | 'mercadolibre'
    source_id                   VARCHAR(100) NOT NULL,
    url                         TEXT NOT NULL,

    -- Info básica
    title                       TEXT,
    description                 TEXT,                       -- texto completo para NLP
    property_type               VARCHAR(50),                -- casa, departamento, PH
    operation_type              VARCHAR(20) DEFAULT 'venta',
    status                      VARCHAR(50),                -- nuevo, usado, a estrenar

    -- Precio
    price                       NUMERIC(15,2),
    currency                    VARCHAR(10),                -- USD, ARS
    expenses                    NUMERIC(15,2),              -- expensas
    expenses_currency           VARCHAR(10),
    price_per_sqm_covered       NUMERIC(15,2),              -- calculado
    price_per_sqm_total         NUMERIC(15,2),              -- calculado
    price_per_room              NUMERIC(15,2),              -- calculado

    -- Superficie
    total_sqm                   NUMERIC(10,2),
    covered_sqm                 NUMERIC(10,2),
    semi_covered_sqm            NUMERIC(10,2),
    ratio_covered_total         NUMERIC(5,4),               -- calculado

    -- Ambientes
    rooms                       INTEGER,                    -- ambientes
    bedrooms                    INTEGER,                    -- dormitorios
    bathrooms                   INTEGER,                    -- baños
    toilettes                   INTEGER,
    garages                     INTEGER,                    -- cocheras

    -- Edificio
    floor                       INTEGER,                    -- piso
    building_floors             INTEGER,                    -- pisos del edificio
    age_years                   INTEGER,                    -- antigüedad en años
    orientation                 VARCHAR(50),                -- N, S, E, O, NE, NO, SE, SO
    luminosity                  VARCHAR(50),                -- muy luminoso, luminoso, etc.

    -- Amenities (boolean)
    has_balcony                 BOOLEAN,
    has_terrace                 BOOLEAN,
    has_garden                  BOOLEAN,
    has_pool                    BOOLEAN,
    has_gym                     BOOLEAN,
    has_security_24h            BOOLEAN,
    has_sum                     BOOLEAN,
    has_laundry                 BOOLEAN,
    has_elevator                BOOLEAN,
    has_storage_room            BOOLEAN,                    -- baulera
    has_heating                 BOOLEAN,
    has_ac                      BOOLEAN,
    has_gas                     BOOLEAN,
    has_hot_water               BOOLEAN,
    has_video_tour              BOOLEAN,

    -- Aptitudes
    pets_allowed                BOOLEAN,
    professional_allowed        BOOLEAN,
    bank_allowed                BOOLEAN,
    credit_allowed              BOOLEAN,

    -- Vista y posición
    view_type                   VARCHAR(100),               -- rio, parque, calle, ciudad
    position                    VARCHAR(50),                -- frente, contrafrente, interno, lateral

    -- Ubicación
    address                     TEXT,
    neighborhood                VARCHAR(200),
    normalized_neighborhood     VARCHAR(200),               -- normalizado via Georef
    district                    VARCHAR(200),               -- partido
    province                    VARCHAR(100),
    amba_zone                   VARCHAR(50),                -- CABA, GBA Norte, GBA Sur, GBA Oeste
    latitude                    NUMERIC(10,7),
    longitude                   NUMERIC(10,7),

    -- Enriquecimiento geoespacial (OpenStreetMap)
    distance_to_subway_m        INTEGER,
    nearest_subway_station      VARCHAR(200),
    distance_to_train_m         INTEGER,
    nearest_train_station       VARCHAR(200),
    distance_to_park_m          INTEGER,
    nearest_park                VARCHAR(200),
    distance_to_obelisk_m       INTEGER,                    -- distancia al centro

    -- Vendedor
    seller_name                 VARCHAR(200),
    seller_type                 VARCHAR(50),                -- inmobiliaria, particular
    seller_phone                VARCHAR(100),
    seller_id                   VARCHAR(100),

    -- Historial de precios (JSONB, una entrada por día, sin duplicados)
    -- Formato: [{"date": "2024-01-15", "price": 150000, "currency": "USD"}, ...]
    price_history               JSONB DEFAULT '[]'::jsonb,
    original_price              NUMERIC(15,2),              -- precio del primer scraping
    price_change_count          INTEGER DEFAULT 0,          -- veces que cambió el precio
    last_price_change_at        DATE,                       -- fecha del último cambio
    price_change_pct            NUMERIC(8,2),               -- % variación desde precio original

    -- Estado de venta
    sale_status                 VARCHAR(20) DEFAULT 'active', -- active | sold | removed
    sold_at                     TIMESTAMP,                  -- cuando se detectó como vendida

    -- Visitas (solo MercadoLibre cuando está disponible)
    ml_visits                   INTEGER,

    -- Metadatos de publicación
    published_at                TIMESTAMP,
    updated_at                  TIMESTAMP,
    days_on_market              INTEGER,                    -- calculado
    photos_count                INTEGER,
    times_updated               INTEGER DEFAULT 0,
    listing_quality_score       NUMERIC(5,2),              -- calculado (0-100)

    -- Metadatos de scraping
    scraped_at                  TIMESTAMP DEFAULT NOW(),
    last_scraped_at             TIMESTAMP DEFAULT NOW(),
    is_active                   BOOLEAN DEFAULT TRUE,

    UNIQUE(source, source_id)
);

-- Imágenes
CREATE TABLE IF NOT EXISTS property_images (
    id                          SERIAL PRIMARY KEY,
    property_id                 INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    url                         TEXT NOT NULL,
    local_path                  TEXT,
    image_order                 INTEGER,
    scraped_at                  TIMESTAMP DEFAULT NOW(),
    UNIQUE(property_id, url)
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_properties_sale_status  ON properties(sale_status);
CREATE INDEX IF NOT EXISTS idx_properties_price_hist   ON properties USING gin(price_history);

CREATE INDEX IF NOT EXISTS idx_properties_source       ON properties(source);
CREATE INDEX IF NOT EXISTS idx_properties_type         ON properties(property_type);
CREATE INDEX IF NOT EXISTS idx_properties_neighborhood ON properties(normalized_neighborhood);
CREATE INDEX IF NOT EXISTS idx_properties_district     ON properties(district);
CREATE INDEX IF NOT EXISTS idx_properties_amba_zone    ON properties(amba_zone);
CREATE INDEX IF NOT EXISTS idx_properties_price        ON properties(price, currency);
CREATE INDEX IF NOT EXISTS idx_properties_location     ON properties(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_properties_active       ON properties(is_active);
CREATE INDEX IF NOT EXISTS idx_images_prop             ON property_images(property_id);
