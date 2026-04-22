-- =============================================================================
-- schema.sql — Base de datos ISAT InSAR
-- PostgreSQL 14+  con extensión PostGIS para datos geoespaciales
-- =============================================================================

-- Habilitar PostGIS (ejecutar una vez como superusuario)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Tabla: satellites
-- Catálogo de satélites disponibles
-- =============================================================================
CREATE TABLE IF NOT EXISTS satellites (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50)  NOT NULL UNIQUE,   -- ej: "SENTINEL-1A"
    wavelength  NUMERIC(6,4) NOT NULL,           -- longitud de onda en cm
    orbit_type  VARCHAR(20)  NOT NULL,           -- "ascending" | "descending"
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

INSERT INTO satellites (name, wavelength, orbit_type) VALUES
    ('SENTINEL-1A', 5.5465, 'ascending'),
    ('SENTINEL-1B', 5.5465, 'descending')
ON CONFLICT DO NOTHING;


-- =============================================================================
-- Tabla: image_pairs
-- Par de imágenes Sentinel-1 que forman un interferograma
-- =============================================================================
CREATE TABLE IF NOT EXISTS image_pairs (
    id                UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    satellite_id      INT          NOT NULL REFERENCES satellites(id),
    reference_date    DATE         NOT NULL,    -- fecha imagen maestra
    secondary_date    DATE         NOT NULL,    -- fecha imagen esclava
    temporal_baseline INT          NOT NULL     -- diferencia en días
        GENERATED ALWAYS AS (secondary_date - reference_date) STORED,
    reference_path    TEXT         NOT NULL,    -- ruta del archivo .zip/.SAFE
    secondary_path    TEXT         NOT NULL,
    track             INT,                      -- número de track relativo
    frame             INT,                      -- número de frame
    aoi               GEOMETRY(Polygon, 4326),  -- área de interés en WGS84
    uploaded_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    uploaded_by       VARCHAR(100),

    CONSTRAINT valid_dates CHECK (secondary_date > reference_date)
);

CREATE INDEX IF NOT EXISTS idx_image_pairs_dates
    ON image_pairs (reference_date, secondary_date);
CREATE INDEX IF NOT EXISTS idx_image_pairs_aoi
    ON image_pairs USING GIST (aoi);


-- =============================================================================
-- Tabla: processing_jobs
-- Registro de cada ejecución del pipeline ISCE2
-- =============================================================================
CREATE TABLE IF NOT EXISTS processing_jobs (
    id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    image_pair_id   UUID         NOT NULL REFERENCES image_pairs(id) ON DELETE CASCADE,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_secs   INT
        GENERATED ALWAYS AS (
            EXTRACT(EPOCH FROM (finished_at - started_at))::INT
        ) STORED,
    error_message   TEXT,
    isce_version    VARCHAR(30),
    server_host     VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status       ON processing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_pair         ON processing_jobs (image_pair_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created      ON processing_jobs (created_at DESC);


-- =============================================================================
-- Tabla: deformation_maps
-- Resultado final: mapa de deformación generado por el pipeline
-- =============================================================================
CREATE TABLE IF NOT EXISTS deformation_maps (
    id                UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id            UUID         NOT NULL UNIQUE REFERENCES processing_jobs(id) ON DELETE CASCADE,
    image_path        TEXT         NOT NULL,             -- ruta local del PNG
    image_data        BYTEA,                             -- datos binarios del PNG (opcional)
    mean_coherence    NUMERIC(5,4),                      -- coherencia media [0-1]
    max_deformation   NUMERIC(8,3),                      -- deformación máxima [cm]
    min_deformation   NUMERIC(8,3),                      -- deformación mínima [cm]
    bounding_box      GEOMETRY(Polygon, 4326),           -- área cubierta en WGS84
    pixel_width       INT,                               -- ancho en píxeles
    pixel_height      INT,                               -- alto en píxeles
    wavelength_cm     NUMERIC(6,4),                      -- λ usada para conversión
    colormap          VARCHAR(30)  DEFAULT 'RdBu_r',     -- colormap matplotlib
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_defmaps_job
    ON deformation_maps (job_id);
CREATE INDEX IF NOT EXISTS idx_defmaps_bbox
    ON deformation_maps USING GIST (bounding_box);
CREATE INDEX IF NOT EXISTS idx_defmaps_coherence
    ON deformation_maps (mean_coherence DESC);


-- =============================================================================
-- Vista: v_results
-- Vista consolidada para consultar resultados completos fácilmente
-- =============================================================================
CREATE OR REPLACE VIEW v_results AS
SELECT
    dm.id                                   AS map_id,
    pj.id                                   AS job_id,
    ip.reference_date,
    ip.secondary_date,
    ip.temporal_baseline                    AS baseline_days,
    s.name                                  AS satellite,
    pj.status,
    pj.duration_secs,
    dm.mean_coherence,
    dm.max_deformation,
    dm.min_deformation,
    dm.image_path,
    ST_AsText(dm.bounding_box)              AS bbox_wkt,
    dm.created_at
FROM deformation_maps dm
JOIN processing_jobs  pj ON pj.id = dm.job_id
JOIN image_pairs      ip ON ip.id = pj.image_pair_id
JOIN satellites        s ON s.id  = ip.satellite_id
ORDER BY dm.created_at DESC;


-- =============================================================================
-- Función: register_job_result()
-- Llamada por el servidor cuando el Docker ISCE2 devuelve el resultado
-- =============================================================================
CREATE OR REPLACE FUNCTION register_job_result(
    p_job_id         UUID,
    p_image_path     TEXT,
    p_image_data     BYTEA,
    p_coherence      NUMERIC,
    p_max_def        NUMERIC,
    p_min_def        NUMERIC,
    p_bbox_wkt       TEXT,
    p_pixel_width    INT,
    p_pixel_height   INT
)
RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE
    v_map_id UUID;
BEGIN
    -- Marcar el job como completado
    UPDATE processing_jobs
    SET
        status      = 'done',
        finished_at = now()
    WHERE id = p_job_id;

    -- Insertar mapa de deformación
    INSERT INTO deformation_maps (
        job_id, image_path, image_data,
        mean_coherence, max_deformation, min_deformation,
        bounding_box, pixel_width, pixel_height
    ) VALUES (
        p_job_id, p_image_path, p_image_data,
        p_coherence, p_max_def, p_min_def,
        ST_GeomFromText(p_bbox_wkt, 4326),
        p_pixel_width, p_pixel_height
    )
    RETURNING id INTO v_map_id;

    RETURN v_map_id;
END;
$$;


-- =============================================================================
-- Función: mark_job_failed()
-- Llamada por el servidor cuando el pipeline devuelve error
-- =============================================================================
CREATE OR REPLACE FUNCTION mark_job_failed(
    p_job_id       UUID,
    p_error_msg    TEXT
)
RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE processing_jobs
    SET
        status        = 'failed',
        finished_at   = now(),
        error_message = p_error_msg
    WHERE id = p_job_id;
END;
$$;