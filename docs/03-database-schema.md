# Deliverable 4 — Database Schema (PostgreSQL + PostGIS + pgvector)

Design goals: normalized (one row per real thing), spatially aware, embedding-ready, multi-estate from day one (cheap now, painful to retrofit later), and **confidence stored next to every estimate**. Environmental data is kept permanently (it's the training signal); images obey the 12-month floor.

> DDL below is illustrative of the final shape; the authoritative version lives in Alembic migrations. Extensions: `CREATE EXTENSION postgis; CREATE EXTENSION vector;`

## Entity overview

```
estates ─┬─< cameras ─┬─< images ─┬─< detections ─┬─< detection_individual >─ individuals
         │            │           │               └── (embedding vector)
         │            └─< env_snapshots            
         ├─< stands (shooting positions / approach geometry)
         └─< users
cameras ─< forecasts        species (reference)        correlations
forecasts ─< forecast_outcomes (calibration)           sync_log        model_runs
```

## Core tables

```sql
-- Tenancy / property -------------------------------------------------
CREATE TABLE estates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  timezone      text NOT NULL DEFAULT 'Europe/Madrid',
  centroid      geometry(Point,4326),          -- for default map view & weather
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estate_id     uuid REFERENCES estates(id),
  email         text UNIQUE NOT NULL,
  password_hash text NOT NULL,                 -- Argon2
  role          text NOT NULL DEFAULT 'admin'  CHECK (role IN ('admin','member','viewer')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Cameras & stands ---------------------------------------------------
CREATE TABLE cameras (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estate_id     uuid NOT NULL REFERENCES estates(id),
  spypoint_id   text UNIQUE,                    -- SPYPOINT device id
  name          text NOT NULL,
  location      geometry(Point,4326),           -- GPS (auto from SPYPOINT, draggable)
  altitude_m    real,
  model         text,
  battery_pct   int,
  signal_pct    int,
  last_sync_at  timestamptz,
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON cameras USING gist (location);

-- A camera can cover one or more stands (shooting positions). Wind logic needs geometry.
CREATE TABLE stands (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estate_id            uuid NOT NULL REFERENCES estates(id),
  camera_id            uuid REFERENCES cameras(id),
  name                 text NOT NULL,           -- "Piedras Lisas North"
  location             geometry(Point,4326),
  shooting_dirs_deg    int[],                    -- lanes the hunter can shoot
  approach_dirs_deg    int[],                    -- where animals typically come from
  notes                text
);
CREATE INDEX ON stands USING gist (location);

-- Species reference (European set only) ------------------------------
CREATE TABLE species (
  id            text PRIMARY KEY,               -- 'sus_scrofa'
  common_name   text NOT NULL,                  -- 'Wild Boar'
  group_name    text,                           -- 'ungulate','carnivore','bird'...
  icon          text, color  text,
  is_priority   boolean NOT NULL DEFAULT false
);

-- Images -------------------------------------------------------------
CREATE TABLE images (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id         uuid NOT NULL REFERENCES cameras(id),
  spypoint_photo_id text UNIQUE,
  captured_at       timestamptz NOT NULL,        -- real capture time (drives enrichment)
  original_path     text,                        -- local path, downloaded (not just URL)
  annotated_path    text,
  cdn_url           text,                        -- kept for reference/backfill
  file_hash         text,                        -- dedupe
  width int, height int,
  is_empty_frame    boolean,                     -- wind/vegetation trigger
  processed_at      timestamptz,                 -- AI done?
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON images (camera_id, captured_at DESC);
CREATE INDEX ON images (processed_at) WHERE processed_at IS NULL;

-- Detections (one row per animal in a frame) -------------------------
CREATE TABLE detections (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_id      uuid NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  species_id    text REFERENCES species(id),
  species_conf  real,                            -- 0..1, always present
  sex           text CHECK (sex IN ('male','female','unknown')) DEFAULT 'unknown',
  sex_conf      real,
  age_class     text CHECK (age_class IN ('juvenile','young_adult','mature_adult','old','unknown')) DEFAULT 'unknown',
  age_conf      real,
  group_size    int,
  group_type    text,                            -- 'single','sow_and_piglets','deer_group'...
  bbox          jsonb,                           -- [x,y,w,h] normalized
  embedding     vector(512),                     -- re-ID; dim depends on chosen model
  model_run_id  uuid REFERENCES model_runs(id),  -- which model version produced this
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON detections (species_id);
CREATE INDEX ON detections USING hnsw (embedding vector_cosine_ops);  -- re-ID search

-- Individuals (recurring named animals) ------------------------------
CREATE TABLE individuals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estate_id     uuid NOT NULL REFERENCES estates(id),
  label         text NOT NULL,                   -- "Large Male Boar #3"
  species_id    text REFERENCES species(id),
  notes         text,
  thumbnail_path text,
  first_seen    timestamptz,
  last_seen     timestamptz,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','missing','archived')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE detection_individual (   -- M:N with confidence + human confirmation
  detection_id  uuid REFERENCES detections(id) ON DELETE CASCADE,
  individual_id uuid REFERENCES individuals(id) ON DELETE CASCADE,
  match_conf    real NOT NULL,
  confirmed_by_user boolean NOT NULL DEFAULT false,
  PRIMARY KEY (detection_id, individual_id)
);

-- Environment snapshots (permanent; the training signal) -------------
CREATE TABLE env_snapshots (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id         uuid NOT NULL REFERENCES cameras(id),
  observed_at       timestamptz NOT NULL,        -- matches image.captured_at
  source            text NOT NULL,               -- 'open-meteo-archive' | 'forecast'
  temp_c real, humidity_pct real, pressure_hpa real,
  wind_speed_kmh real, wind_gust_kmh real, wind_dir_deg int,
  rain_mm real, cloud_cover_pct int,
  moon_phase text, moon_illum_pct real, moon_rise timestamptz, moon_set timestamptz,
  sunrise timestamptz, sunset timestamptz,
  civil_twilight_end timestamptz, nautical_twilight_end timestamptz,
  darkness_minutes int,
  UNIQUE (camera_id, observed_at)
);
CREATE INDEX ON env_snapshots (camera_id, observed_at);

-- Forecasts & calibration -------------------------------------------
CREATE TABLE forecasts (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id        uuid REFERENCES cameras(id),
  stand_id         uuid REFERENCES stands(id),
  target_date      date NOT NULL,
  species_id       text REFERENCES species(id),
  individual_id    uuid REFERENCES individuals(id),
  probability      real NOT NULL,                 -- calibrated 0..1
  best_window_start timetz, best_window_end timetz,
  confidence       real,
  factors          jsonb,                         -- {"moon_illum":-0.3,"wind":"favorable",...} for the "why"
  model_run_id     uuid REFERENCES model_runs(id),
  generated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON forecasts (target_date, camera_id);

CREATE TABLE forecast_outcomes (   -- did it happen? drives "verified correct 71% of nights"
  forecast_id   uuid REFERENCES forecasts(id) ON DELETE CASCADE,
  occurred      boolean,
  actual_count  int,
  evaluated_at  timestamptz,
  PRIMARY KEY (forecast_id)
);

-- Correlations stated as sentences ----------------------------------
CREATE TABLE correlations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  estate_id     uuid REFERENCES estates(id),
  scope         text,                            -- 'global' | species id | camera id
  statement     text NOT NULL,                   -- "Boar arrive ~40 min later within 3 days of full moon"
  strength      real,                            -- effect size / confidence
  sample_size   int,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Ops -----------------------------------------------------------------
CREATE TABLE model_runs (        -- reproducibility: which weights produced which output
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind          text,                            -- 'detector','classifier','forecast'
  name          text, version text,
  started_at    timestamptz, finished_at timestamptz,
  metrics       jsonb
);

CREATE TABLE sync_log (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id     uuid REFERENCES cameras(id),
  photos_synced int, images_downloaded int,
  status        text, error text,
  started_at    timestamptz, finished_at timestamptz
);
```

## Notes & decisions baked in

- **`embedding vector(512)`** is a placeholder — the exact dimension follows the chosen re-ID backbone (e.g., 512/768/2048). Easy to set once the AI model is confirmed.
- **Confidence is non-null by convention** on every estimate (`species_conf`, `sex_conf`, `age_conf`, `match_conf`, forecast `confidence`). The UI contract is "no number without a confidence."
- **`env_snapshots` is per camera × capture time**, written at ingest from the **archive** endpoint for the real timestamp — this is the direct fix for audit bug C1.
- **Retention (decision: server-only):** a scheduled job prunes `images.original_path` files older than `MEDIA_RETENTION_DAYS` — a **small rolling window on the laptop** (dev/test) and **≥365 on the Phase-2 server** (the real archive). In all cases the `detections` and `env_snapshots` rows are **kept forever** — we lose pixels, never the signal. Tiny annotated thumbnails can be retained longer than originals.
- **PostGIS** powers proximity ("could Camera A 22:00 and Camera B 23:15 be the same animal?") and movement corridors; **pgvector HNSW** powers re-ID nearest-neighbour search.
- **Multi-estate** is present but invisible until needed — a single seeded estate (Piedras Lisas) keeps Phase-1 UX single-tenant.
