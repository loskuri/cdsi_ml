-- ============================================================
-- MIGRACIÓN v2: price_history JSONB + sale_status + ml_visits
-- Ejecutar solo si ya existe la base de datos de v1
-- ============================================================

BEGIN;

-- 1. Eliminar tabla price_history separada (reemplazada por columna JSONB)
DROP TABLE IF EXISTS price_history;

-- 2. Nuevos campos de historial de precios
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS price_history          JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS original_price         NUMERIC(15,2),
    ADD COLUMN IF NOT EXISTS price_change_count     INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_price_change_at   DATE,
    ADD COLUMN IF NOT EXISTS price_change_pct       NUMERIC(8,2);

-- 3. Campos de estado de venta
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS sale_status            VARCHAR(20) DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS sold_at                TIMESTAMP;

-- 4. Visitas MercadoLibre
ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS ml_visits              INTEGER;

-- 5. Inicializar original_price con el precio actual de propiedades existentes
UPDATE properties
SET original_price  = price,
    price_history   = CASE
                        WHEN price IS NOT NULL THEN
                            jsonb_build_array(
                                jsonb_build_object(
                                    'date',     TO_CHAR(scraped_at, 'YYYY-MM-DD'),
                                    'price',    price,
                                    'currency', currency
                                )
                            )
                        ELSE '[]'::jsonb
                      END
WHERE original_price IS NULL;

-- 6. Inicializar sale_status en propiedades existentes
UPDATE properties
SET sale_status = CASE
                    WHEN is_active = TRUE  THEN 'active'
                    WHEN is_active = FALSE THEN 'removed'
                  END
WHERE sale_status IS NULL OR sale_status = '';

-- 7. UNIQUE constraint en property_images (si no existe)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'property_images_property_id_url_key'
    ) THEN
        ALTER TABLE property_images ADD CONSTRAINT property_images_property_id_url_key UNIQUE (property_id, url);
    END IF;
END $$;

-- 8. Nuevos índices
CREATE INDEX IF NOT EXISTS idx_properties_sale_status ON properties(sale_status);
CREATE INDEX IF NOT EXISTS idx_properties_price_hist  ON properties USING gin(price_history);

COMMIT;
