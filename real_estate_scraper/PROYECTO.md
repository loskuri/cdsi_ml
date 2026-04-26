# Real Estate Scraper AMBA - Documentación Técnica

## Descripción general

Sistema de extracción, almacenamiento y enriquecimiento de datos de inmuebles en venta en el Área Metropolitana de Buenos Aires (AMBA). Los datos se obtienen semanalmente de Zonaprop y MercadoLibre Inmuebles, se almacenan en PostgreSQL y las imágenes en disco, con el objetivo de construir un modelo predictivo de precios.

---

## Fuentes de datos

| Fuente | Método | Tipo de propiedad |
|--------|--------|------------------|
| Zonaprop | Playwright (scraping JS) | Casa, Departamento, PH |
| MercadoLibre | API pública REST | Casa, Departamento, PH |

### Zonaprop
Zonaprop no tiene API pública. Se utiliza **Playwright** (automatización de navegador) para renderizar el contenido JavaScript y extraer los datos. El scraper navega por las páginas de resultados paginando hasta obtener todos los listados de AMBA, luego visita cada propiedad individualmente para extraer el detalle completo.

### MercadoLibre
MercadoLibre dispone de una API pública sin autenticación para búsquedas. Se utiliza el endpoint `/sites/MLA/search` con filtros por categoría de inmuebles (`MLA1459`) y ubicación AMBA. El detalle de cada propiedad se obtiene vía `/items/{id}`.

---

## Variables capturadas (~70 variables por propiedad)

### Identificación y fuente
- `source`: Origen del dato (zonaprop / mercadolibre)
- `source_id`: ID único en la fuente
- `url`: URL del listado
- `scraped_at`, `last_scraped_at`: Timestamps de scraping

### Información básica
- `title`: Título del anuncio
- `description`: Descripción completa (texto libre, útil para NLP)
- `property_type`: casa | departamento | PH
- `status`: nuevo | a estrenar | usado

### Precio
- `price`, `currency`: Precio y moneda (USD / ARS)
- `expenses`, `expenses_currency`: Expensas
- `price_per_sqm_covered`: Precio por m² cubierto *(calculado)*
- `price_per_sqm_total`: Precio por m² total *(calculado)*
- `price_per_room`: Precio por ambiente *(calculado)*

### Superficie
- `total_sqm`: Superficie total en m²
- `covered_sqm`: Superficie cubierta en m²
- `semi_covered_sqm`: Superficie semicubierta en m²
- `ratio_covered_total`: Ratio cubierto/total *(calculado)*

### Ambientes
- `rooms`: Cantidad de ambientes
- `bedrooms`: Dormitorios
- `bathrooms`: Baños
- `toilettes`: Toilettes
- `garages`: Cocheras

### Características del edificio
- `floor`: Piso de la unidad
- `building_floors`: Cantidad de pisos del edificio
- `age_years`: Antigüedad en años
- `orientation`: Orientación (N, S, E, O, NE, NO, SE, SO)
- `luminosity`: Nivel de luminosidad

### Amenities (booleanos)
- `has_balcony`, `has_terrace`, `has_garden`
- `has_pool`, `has_gym`, `has_security_24h`
- `has_sum`, `has_laundry`, `has_elevator`
- `has_storage_room` (baulera)
- `has_heating`, `has_ac`, `has_gas`, `has_hot_water`
- `has_video_tour`

### Aptitudes
- `pets_allowed`: Apto mascotas
- `professional_allowed`: Apto profesional
- `bank_allowed`: Apto banco
- `credit_allowed`: Apto crédito

### Vista y posición
- `view_type`: Tipo de vista (río, parque, calle, ciudad)
- `position`: frente | contrafrente | interno | lateral

### Ubicación
- `address`: Dirección del inmueble
- `neighborhood`: Barrio según la fuente
- `normalized_neighborhood`: Barrio normalizado via API Georef Argentina
- `district`: Partido (GBA) o Comuna (CABA)
- `province`: Provincia
- `amba_zone`: CABA | GBA Norte | GBA Sur | GBA Oeste *(calculado)*
- `latitude`, `longitude`: Coordenadas geográficas

### Enriquecimiento geoespacial (OpenStreetMap)
- `distance_to_subway_m`: Distancia en metros a la estación de subte más cercana
- `nearest_subway_station`: Nombre de la estación
- `distance_to_train_m`: Distancia al tren más cercano
- `nearest_train_station`: Nombre de la estación
- `distance_to_park_m`: Distancia al parque/plaza más cercano
- `nearest_park`: Nombre del parque
- `distance_to_obelisk_m`: Distancia al Obelisco (centro de CABA)

### Vendedor
- `seller_name`: Nombre de la inmobiliaria o particular
- `seller_type`: inmobiliaria | particular
- `seller_phone`: Teléfono de contacto
- `seller_id`: ID del vendedor en la plataforma

### Historial y evolución de precio
- `price_history`: Array JSONB con una entrada por día `[{"date": "2024-01-15", "price": 150000, "currency": "USD"}, ...]`
- `original_price`: Precio del primer scraping
- `price_change_count`: Cantidad de veces que cambió el precio
- `last_price_change_at`: Fecha del último cambio de precio
- `price_change_pct`: Variación porcentual acumulada respecto al precio original *(calculado)*

### Estado de venta
- `sale_status`: `active` | `sold` | `removed`
- `sold_at`: Timestamp de cuando se detectó como vendida

### Visitas
- `ml_visits`: Cantidad de visitas a la publicación (solo MercadoLibre, cuando disponible)

### Metadatos de publicación
- `published_at`: Fecha de publicación original
- `updated_at`: Última actualización del anuncio
- `days_on_market`: Días desde la publicación *(calculado)*
- `photos_count`: Cantidad de fotos del anuncio
- `times_updated`: Cantidad de veces que se scrapeó con cambios
- `listing_quality_score`: Score de calidad del anuncio (0-100) *(calculado)*

---

## Tablas adicionales

### `property_images`
Referencia a cada imagen de cada propiedad.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| property_id | FK | Referencia a la propiedad |
| url | TEXT | URL original de la imagen |
| local_path | TEXT | Ruta en disco dentro del volumen Docker |
| image_order | INTEGER | Orden de la imagen en el anuncio |

---

## Arquitectura

```
real_estate_scraper/
├── scrapers/
│   ├── zonaprop.py          # Playwright: navega y extrae datos de Zonaprop
│   └── mercadolibre.py      # Requests: consume la API pública de ML
├── enrichment/
│   ├── osm.py               # OpenStreetMap: distancias a subte, tren, parques
│   └── georef.py            # API Georef Argentina: normalización de barrios
├── models/
│   ├── schema.sql           # DDL completo de PostgreSQL (instalación nueva)
│   └── migration_v2.sql     # Migración para bases existentes
├── storage/
│   ├── database.py          # Conexión y operaciones CRUD en PostgreSQL
│   └── images.py            # Descarga y almacenamiento de imágenes en disco
├── images/                  # Volumen Docker con imágenes descargadas
│   └── {source}_{id}/
│       ├── 1.jpg
│       └── 2.jpg
├── logs/                    # Logs de ejecución
├── scheduler.py             # Scheduler semanal (APScheduler)
├── main.py                  # Punto de entrada manual
├── qa.py                    # Validación de calidad de datos post-scraping
├── config.py                # Configuración centralizada
├── docker-compose.yml       # PostgreSQL + Scraper en contenedores
├── Dockerfile               # Imagen del scraper
├── requirements.txt
├── .gitignore
└── .env                     # Variables de entorno (no commitear)
```

---

## Stack tecnológico

| Componente | Tecnología | Motivo |
|------------|-----------|--------|
| Lenguaje | Python 3.11 | Ecosistema de scraping y ML |
| Scraping JS | Playwright | Renderiza SPAs, mejor anti-bot |
| Scraping API | Requests + httpx | Liviano para APIs REST |
| Base de datos | PostgreSQL 15 | Robusto, soporta JSON, escalable |
| ORM / queries | psycopg2 | Driver nativo PostgreSQL |
| Scheduler | APScheduler | Ejecución semanal sin cron externo |
| Contenedores | Docker + Compose | Entorno reproducible y portable |
| Geoespacial | Overpy (OSM) | Datos abiertos de infraestructura |
| Normalización | API Georef | Datos oficiales del gobierno argentino |

---

## Flujo de ejecución semanal

```
Scheduler (domingo 2AM)
    │
    ├── Zonaprop scraper
    │       ├── Busca todos los listados AMBA (casa, depto, PH)
    │       ├── Pagina por resultados
    │       └── Extrae detalle de cada propiedad
    │
    ├── MercadoLibre scraper
    │       ├── Consulta API pública
    │       ├── Filtra por AMBA y tipos de propiedad
    │       └── Obtiene detalle via /items/{id}
    │
    ├── Enriquecimiento geoespacial
    │       ├── Calcula distancias via OSM (subte, tren, parques)
    │       └── Normaliza barrios via Georef Argentina
    │
    ├── Almacenamiento
    │       ├── Upsert en PostgreSQL (nueva o actualización)
    │       ├── Registra cambio de precio si corresponde
    │       └── Descarga imágenes nuevas a disco
    │
    └── Log de resultados
```

---

## Variables de entorno (.env)

```env
POSTGRES_USER=realestate
POSTGRES_PASSWORD=realestate123
POSTGRES_DB=real_estate
SCHEDULE_DAY=sunday
SCHEDULE_HOUR=2
```

---

## Uso

```bash
# Copiar variables de entorno
cp .env.example .env

# Levantar servicios
docker-compose up -d

# Ejecutar scraping manual (sin esperar el scheduler)
docker-compose exec scraper python main.py

# Ver logs
docker-compose logs -f scraper

# Acceder a la base de datos
docker-compose exec db psql -U realestate -d real_estate
```

---

## Consideraciones para el modelo predictivo

Los datos están diseñados para facilitar la construcción de un modelo de predicción de precios:

- **Variables numéricas listas para usar**: precio/m², superficie, ambientes, distancias
- **Variables categóricas**: zona AMBA, tipo de propiedad, barrio normalizado
- **Variables booleanas**: amenities, aptitudes
- **Series temporales**: historial de precios por propiedad
- **Texto**: descripción completa para feature engineering con NLP
- **Imágenes**: disponibles para modelos de visión computacional
- **Geoespacial**: coordenadas y distancias a puntos de interés

El campo `listing_quality_score` penaliza propiedades con datos incompletos, útil para filtrar el dataset de entrenamiento.
