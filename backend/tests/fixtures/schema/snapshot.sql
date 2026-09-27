-- GameSense schema at 0030_harvest_and_people, as a migrated database has it.
-- Refresh: cd backend && python -m tests.schema_snapshot
--
-- PostgreSQL database dump
--




SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: app_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_settings (
    key character varying NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: camera_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.camera_accounts (
    id uuid NOT NULL,
    estate_id uuid NOT NULL,
    owner_user_id uuid,
    former_owner character varying,
    label character varying,
    provider character varying DEFAULT 'spypoint'::character varying NOT NULL,
    username character varying NOT NULL,
    password_enc character varying NOT NULL,
    active boolean NOT NULL,
    ubox_min_interval_seconds integer DEFAULT 60 NOT NULL,
    ubox_max_images_per_day integer DEFAULT 500 NOT NULL,
    last_sync_at timestamp with time zone,
    last_attempt_at timestamp with time zone,
    last_ok_at timestamp with time zone,
    last_error text,
    reported_cameras integer,
    session_enc text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_camera_accounts_provider_valid CHECK (((provider)::text = ANY (ARRAY[('spypoint'::character varying)::text, ('ubox'::character varying)::text]))),
    CONSTRAINT ck_camera_accounts_ubox_daily_limit_valid CHECK (((ubox_max_images_per_day >= 1) AND (ubox_max_images_per_day <= 5000))),
    CONSTRAINT ck_camera_accounts_ubox_interval_valid CHECK (((ubox_min_interval_seconds >= 10) AND (ubox_min_interval_seconds <= 3600)))
);


--
-- Name: camera_nights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.camera_nights (
    id uuid NOT NULL,
    camera_id uuid NOT NULL,
    night date NOT NULL,
    exposure_state character varying NOT NULL,
    frames integer NOT NULL,
    empty_frames integer NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_camera_nights_exposure_state_valid CHECK (((exposure_state)::text = ANY (ARRAY[('CONFIRMED'::character varying)::text, ('PRESUMED_UP'::character varying)::text, ('UNPROCESSED'::character varying)::text, ('UNKNOWN'::character varying)::text])))
);


--
-- Name: camera_views; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.camera_views (
    user_id uuid NOT NULL,
    camera_id uuid NOT NULL,
    seen_at timestamp with time zone NOT NULL
);


--
-- Name: cameras; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cameras (
    id uuid NOT NULL,
    estate_id uuid NOT NULL,
    account_id uuid,
    spypoint_id character varying,
    ubox_uid character varying,
    name character varying NOT NULL,
    provider_name character varying,
    name_is_custom boolean DEFAULT false NOT NULL,
    lat double precision,
    lon double precision,
    location_is_custom boolean DEFAULT false NOT NULL,
    provider_lat double precision,
    provider_lon double precision,
    altitude_m double precision,
    model character varying,
    battery_pct integer,
    signal_pct integer,
    last_sync_at timestamp with time zone,
    last_report_at timestamp with time zone,
    battery_level character varying,
    sd_used_mb integer,
    sd_total_mb integer,
    photo_count integer,
    photo_limit integer,
    plan_name character varying,
    cycle_end timestamp with time zone,
    active boolean NOT NULL,
    retired_at timestamp with time zone,
    clock_ahead_min integer,
    clock_ok_photos integer,
    photos_listed_to timestamp with time zone,
    photos_gap_from timestamp with time zone,
    photos_gap_to timestamp with time zone,
    fetch_error text,
    import_failures jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_cameras_provider_exclusive CHECK (((spypoint_id IS NULL) OR (ubox_uid IS NULL)))
);


--
-- Name: client_errors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.client_errors (
    id uuid NOT NULL,
    user_id uuid,
    kind character varying(32) NOT NULL,
    message character varying(500) NOT NULL,
    stack text,
    route character varying(200),
    build character varying(64),
    user_agent character varying(300),
    happened_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: correlations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.correlations (
    id uuid NOT NULL,
    estate_id uuid,
    scope character varying,
    statement text NOT NULL,
    strength double precision,
    sample_size integer,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: detection_individual; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detection_individual (
    detection_id uuid NOT NULL,
    individual_id uuid NOT NULL,
    match_conf double precision NOT NULL,
    confirmed_by_user boolean NOT NULL
);


--
-- Name: detections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detections (
    id uuid NOT NULL,
    image_id uuid NOT NULL,
    species_id character varying,
    species_conf double precision,
    sex character varying NOT NULL,
    sex_conf double precision,
    sex_checked_at timestamp with time zone,
    sex_attempts integer NOT NULL,
    age_class character varying NOT NULL,
    age_conf double precision,
    group_size integer,
    group_type character varying,
    bbox jsonb,
    embedding jsonb,
    model_run_id uuid,
    corrected_at timestamp with time zone,
    corrected_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_detections_age_valid CHECK (((age_class)::text = ANY (ARRAY[('juvenile'::character varying)::text, ('young_adult'::character varying)::text, ('mature_adult'::character varying)::text, ('old'::character varying)::text, ('unknown'::character varying)::text]))),
    CONSTRAINT ck_detections_sex_valid CHECK (((sex)::text = ANY (ARRAY[('male'::character varying)::text, ('female'::character varying)::text, ('unknown'::character varying)::text])))
);


--
-- Name: env_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.env_snapshots (
    id uuid NOT NULL,
    camera_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    source character varying NOT NULL,
    temp_c double precision,
    humidity_pct double precision,
    pressure_hpa double precision,
    wind_speed_kmh double precision,
    wind_gust_kmh double precision,
    wind_dir_deg integer,
    rain_mm double precision,
    cloud_cover_pct integer,
    moon_phase character varying,
    moon_illum_pct double precision,
    moon_rise timestamp with time zone,
    moon_set timestamp with time zone,
    sunrise timestamp with time zone,
    sunset timestamp with time zone,
    civil_twilight_end timestamp with time zone,
    nautical_twilight_end timestamp with time zone,
    darkness_minutes integer
);


--
-- Name: estates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.estates (
    id uuid NOT NULL,
    name character varying NOT NULL,
    timezone character varying NOT NULL,
    lat double precision,
    lon double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: forecast_outcomes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecast_outcomes (
    forecast_id uuid NOT NULL,
    occurred boolean,
    actual_count integer,
    evaluated_at timestamp with time zone
);


--
-- Name: forecasts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecasts (
    id uuid NOT NULL,
    camera_id uuid,
    stand_id uuid,
    target_date date NOT NULL,
    species_id character varying,
    individual_id uuid,
    probability double precision NOT NULL,
    best_window_start time with time zone,
    best_window_end time with time zone,
    confidence double precision,
    factors jsonb,
    model_run_id uuid,
    generated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: harvests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.harvests (
    id uuid NOT NULL,
    sit_id uuid,
    stand_id uuid,
    user_id uuid,
    hunter character varying(60) NOT NULL,
    species_id character varying NOT NULL,
    sex character varying DEFAULT 'unknown'::character varying NOT NULL,
    age_class character varying DEFAULT 'unknown'::character varying NOT NULL,
    seal character varying(40),
    weight_kg double precision,
    notes character varying(500),
    taken_at timestamp with time zone NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_harvests_age_valid CHECK (((age_class)::text = ANY (ARRAY[('juvenile'::character varying)::text, ('young_adult'::character varying)::text, ('mature_adult'::character varying)::text, ('old'::character varying)::text, ('unknown'::character varying)::text]))),
    CONSTRAINT ck_harvests_sex_valid CHECK (((sex)::text = ANY (ARRAY[('male'::character varying)::text, ('female'::character varying)::text, ('unknown'::character varying)::text]))),
    CONSTRAINT ck_harvests_weight_valid CHECK (((weight_kg IS NULL) OR ((weight_kg > (0)::double precision) AND (weight_kg < (1000)::double precision))))
);


--
-- Name: images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.images (
    id uuid NOT NULL,
    camera_id uuid NOT NULL,
    spypoint_photo_id character varying,
    ubox_event_id character varying,
    captured_at timestamp with time zone NOT NULL,
    received_at timestamp with time zone,
    original_path character varying,
    thumbnail_path character varying,
    annotated_path character varying,
    cdn_url character varying,
    file_hash character varying,
    download_attempts integer DEFAULT 0 NOT NULL,
    width integer,
    height integer,
    is_empty_frame boolean,
    animal_conf double precision,
    reviewed boolean NOT NULL,
    processed_at timestamp with time zone,
    ai_attempts integer DEFAULT 0 NOT NULL,
    ai_error text,
    ai_failed_at timestamp with time zone,
    detector_conf double precision,
    person_conf double precision,
    vehicle_conf double precision,
    people_cleared boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: individuals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.individuals (
    id uuid NOT NULL,
    estate_id uuid NOT NULL,
    label character varying NOT NULL,
    species_id character varying,
    notes text,
    thumbnail_path character varying,
    first_seen timestamp with time zone,
    last_seen timestamp with time zone,
    status character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_individuals_status_valid CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('missing'::character varying)::text, ('archived'::character varying)::text])))
);


--
-- Name: model_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_runs (
    id uuid NOT NULL,
    kind character varying,
    name character varying,
    version character varying,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    metrics jsonb
);


--
-- Name: notification_prefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_prefs (
    user_id uuid NOT NULL,
    enabled boolean NOT NULL,
    species_ids jsonb NOT NULL,
    muted_camera_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    quiet_start time without time zone,
    quiet_end time without time zone,
    plan_push boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    kind character varying NOT NULL,
    title character varying NOT NULL,
    body text NOT NULL,
    url character varying,
    species_id character varying,
    image_id uuid,
    push_status character varying,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone
);


--
-- Name: photo_notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.photo_notes (
    id uuid NOT NULL,
    image_id uuid NOT NULL,
    user_id uuid,
    text character varying(140),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_subscriptions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    endpoint text NOT NULL,
    p256dh character varying NOT NULL,
    auth character varying NOT NULL,
    user_agent character varying,
    failures integer NOT NULL,
    last_success_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sits (
    id uuid NOT NULL,
    stand_id uuid NOT NULL,
    user_id uuid,
    night date NOT NULL,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    outcome character varying NOT NULL,
    reported_at timestamp with time zone,
    species_seen character varying,
    wind_status character varying,
    wind_text text,
    wind_at timestamp with time zone,
    notes text,
    no_harvest_at timestamp with time zone,
    CONSTRAINT ck_sits_outcome_valid CHECK (((outcome)::text = ANY (ARRAY[('unreported'::character varying)::text, ('nothing'::character varying)::text, ('seen'::character varying)::text, ('shootable_no_shot'::character varying)::text, ('shot'::character varying)::text, ('cancelled'::character varying)::text])))
);


--
-- Name: species; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.species (
    id character varying NOT NULL,
    common_name character varying NOT NULL,
    group_name character varying,
    icon character varying,
    color character varying,
    is_priority boolean NOT NULL,
    huntable boolean DEFAULT true NOT NULL,
    hidden boolean DEFAULT false NOT NULL
);


--
-- Name: stands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stands (
    id uuid NOT NULL,
    estate_id uuid NOT NULL,
    camera_id uuid,
    name character varying NOT NULL,
    lat double precision,
    lon double precision,
    shooting_dirs_deg integer[],
    approach_dirs_deg integer[],
    notes text
);


--
-- Name: sync_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sync_log (
    id uuid NOT NULL,
    camera_id uuid,
    photos_synced integer,
    images_downloaded integer,
    status character varying,
    error text,
    details jsonb,
    started_at timestamp with time zone,
    finished_at timestamp with time zone
);


--
-- Name: terrain_grid; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.terrain_grid (
    id uuid NOT NULL,
    min_lat double precision NOT NULL,
    min_lon double precision NOT NULL,
    max_lat double precision NOT NULL,
    max_lon double precision NOT NULL,
    steps integer NOT NULL,
    elevations jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    estate_id uuid,
    email character varying NOT NULL,
    password_hash character varying NOT NULL,
    role character varying NOT NULL,
    token_version integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_users_role_valid CHECK (((role)::text = ANY (ARRAY[('admin'::character varying)::text, ('member'::character varying)::text, ('viewer'::character varying)::text])))
);


--
-- Name: zones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.zones (
    id uuid NOT NULL,
    estate_id uuid NOT NULL,
    kind character varying NOT NULL,
    name character varying NOT NULL,
    polygon jsonb NOT NULL,
    notes text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_zones_zone_kind_valid CHECK (((kind)::text = ANY (ARRAY[('bedding'::character varying)::text, ('feeding'::character varying)::text, ('water'::character varying)::text, ('no_go'::character varying)::text])))
);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: app_settings pk_app_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT pk_app_settings PRIMARY KEY (key);


--
-- Name: camera_accounts pk_camera_accounts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_accounts
    ADD CONSTRAINT pk_camera_accounts PRIMARY KEY (id);


--
-- Name: camera_nights pk_camera_nights; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_nights
    ADD CONSTRAINT pk_camera_nights PRIMARY KEY (id);


--
-- Name: camera_views pk_camera_views; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_views
    ADD CONSTRAINT pk_camera_views PRIMARY KEY (user_id, camera_id);


--
-- Name: cameras pk_cameras; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT pk_cameras PRIMARY KEY (id);


--
-- Name: client_errors pk_client_errors; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_errors
    ADD CONSTRAINT pk_client_errors PRIMARY KEY (id);


--
-- Name: correlations pk_correlations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correlations
    ADD CONSTRAINT pk_correlations PRIMARY KEY (id);


--
-- Name: detection_individual pk_detection_individual; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detection_individual
    ADD CONSTRAINT pk_detection_individual PRIMARY KEY (detection_id, individual_id);


--
-- Name: detections pk_detections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT pk_detections PRIMARY KEY (id);


--
-- Name: env_snapshots pk_env_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.env_snapshots
    ADD CONSTRAINT pk_env_snapshots PRIMARY KEY (id);


--
-- Name: estates pk_estates; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.estates
    ADD CONSTRAINT pk_estates PRIMARY KEY (id);


--
-- Name: forecast_outcomes pk_forecast_outcomes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_outcomes
    ADD CONSTRAINT pk_forecast_outcomes PRIMARY KEY (forecast_id);


--
-- Name: forecasts pk_forecasts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT pk_forecasts PRIMARY KEY (id);


--
-- Name: harvests pk_harvests; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT pk_harvests PRIMARY KEY (id);


--
-- Name: images pk_images; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT pk_images PRIMARY KEY (id);


--
-- Name: individuals pk_individuals; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.individuals
    ADD CONSTRAINT pk_individuals PRIMARY KEY (id);


--
-- Name: model_runs pk_model_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_runs
    ADD CONSTRAINT pk_model_runs PRIMARY KEY (id);


--
-- Name: notification_prefs pk_notification_prefs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_prefs
    ADD CONSTRAINT pk_notification_prefs PRIMARY KEY (user_id);


--
-- Name: notifications pk_notifications; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT pk_notifications PRIMARY KEY (id);


--
-- Name: photo_notes pk_photo_notes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photo_notes
    ADD CONSTRAINT pk_photo_notes PRIMARY KEY (id);


--
-- Name: push_subscriptions pk_push_subscriptions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT pk_push_subscriptions PRIMARY KEY (id);


--
-- Name: sits pk_sits; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sits
    ADD CONSTRAINT pk_sits PRIMARY KEY (id);


--
-- Name: species pk_species; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.species
    ADD CONSTRAINT pk_species PRIMARY KEY (id);


--
-- Name: stands pk_stands; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stands
    ADD CONSTRAINT pk_stands PRIMARY KEY (id);


--
-- Name: sync_log pk_sync_log; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_log
    ADD CONSTRAINT pk_sync_log PRIMARY KEY (id);


--
-- Name: terrain_grid pk_terrain_grid; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.terrain_grid
    ADD CONSTRAINT pk_terrain_grid PRIMARY KEY (id);


--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);


--
-- Name: zones pk_zones; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT pk_zones PRIMARY KEY (id);


--
-- Name: camera_accounts uq_camera_accounts_provider_username; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_accounts
    ADD CONSTRAINT uq_camera_accounts_provider_username UNIQUE (provider, username);


--
-- Name: camera_nights uq_camera_night; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_nights
    ADD CONSTRAINT uq_camera_night UNIQUE (camera_id, night);


--
-- Name: cameras uq_cameras_spypoint_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT uq_cameras_spypoint_id UNIQUE (spypoint_id);


--
-- Name: cameras uq_cameras_ubox_uid; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT uq_cameras_ubox_uid UNIQUE (ubox_uid);


--
-- Name: env_snapshots uq_env_camera_time; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.env_snapshots
    ADD CONSTRAINT uq_env_camera_time UNIQUE (camera_id, observed_at);


--
-- Name: images uq_images_spypoint_photo_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT uq_images_spypoint_photo_id UNIQUE (spypoint_photo_id);


--
-- Name: images uq_images_ubox_event_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT uq_images_ubox_event_id UNIQUE (ubox_event_id);


--
-- Name: push_subscriptions uq_push_subscriptions_endpoint; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT uq_push_subscriptions_endpoint UNIQUE (endpoint);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: ix_camera_nights_night; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_camera_nights_night ON public.camera_nights USING btree (night);


--
-- Name: ix_client_errors_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_client_errors_created_at ON public.client_errors USING btree (created_at);


--
-- Name: ix_detections_image_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_detections_image_id ON public.detections USING btree (image_id);


--
-- Name: ix_detections_species_image; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_detections_species_image ON public.detections USING btree (species_id, image_id);


--
-- Name: ix_forecasts_date_camera; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_forecasts_date_camera ON public.forecasts USING btree (target_date, camera_id);


--
-- Name: ix_harvests_sit_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_harvests_sit_id ON public.harvests USING btree (sit_id);


--
-- Name: ix_harvests_taken_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_harvests_taken_at ON public.harvests USING btree (taken_at);


--
-- Name: ix_images_camera_captured; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_images_camera_captured ON public.images USING btree (camera_id, captured_at);


--
-- Name: ix_images_camera_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_images_camera_created ON public.images USING btree (camera_id, created_at);


--
-- Name: ix_images_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_images_captured_at ON public.images USING btree (captured_at DESC);


--
-- Name: ix_notifications_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_created ON public.notifications USING btree (user_id, created_at);


--
-- Name: ix_photo_notes_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_photo_notes_created_at ON public.photo_notes USING btree (created_at);


--
-- Name: ix_photo_notes_image_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_photo_notes_image_id ON public.photo_notes USING btree (image_id);


--
-- Name: ix_push_subscriptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_push_subscriptions_user_id ON public.push_subscriptions USING btree (user_id);


--
-- Name: ix_sits_night; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sits_night ON public.sits USING btree (night);


--
-- Name: ix_sits_stand_night; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sits_stand_night ON public.sits USING btree (stand_id, night);


--
-- Name: ix_zones_estate_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_zones_estate_kind ON public.zones USING btree (estate_id, kind);


--
-- Name: uq_camera_accounts_provider_login; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_camera_accounts_provider_login ON public.camera_accounts USING btree (provider, lower((username)::text)) WHERE active;


--
-- Name: uq_sits_stand_night_live; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_sits_stand_night_live ON public.sits USING btree (stand_id, night) WHERE ((outcome)::text <> 'cancelled'::text);


--
-- Name: camera_accounts fk_camera_accounts_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_accounts
    ADD CONSTRAINT fk_camera_accounts_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: camera_accounts fk_camera_accounts_owner_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_accounts
    ADD CONSTRAINT fk_camera_accounts_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: camera_nights fk_camera_nights_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_nights
    ADD CONSTRAINT fk_camera_nights_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: camera_views fk_camera_views_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_views
    ADD CONSTRAINT fk_camera_views_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE CASCADE;


--
-- Name: camera_views fk_camera_views_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.camera_views
    ADD CONSTRAINT fk_camera_views_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cameras fk_cameras_account_id_camera_accounts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT fk_cameras_account_id_camera_accounts FOREIGN KEY (account_id) REFERENCES public.camera_accounts(id);


--
-- Name: cameras fk_cameras_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT fk_cameras_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: client_errors fk_client_errors_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_errors
    ADD CONSTRAINT fk_client_errors_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: correlations fk_correlations_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.correlations
    ADD CONSTRAINT fk_correlations_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: detection_individual fk_detection_individual_detection_id_detections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detection_individual
    ADD CONSTRAINT fk_detection_individual_detection_id_detections FOREIGN KEY (detection_id) REFERENCES public.detections(id) ON DELETE CASCADE;


--
-- Name: detection_individual fk_detection_individual_individual_id_individuals; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detection_individual
    ADD CONSTRAINT fk_detection_individual_individual_id_individuals FOREIGN KEY (individual_id) REFERENCES public.individuals(id) ON DELETE CASCADE;


--
-- Name: detections fk_detections_corrected_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT fk_detections_corrected_by_users FOREIGN KEY (corrected_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: detections fk_detections_image_id_images; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT fk_detections_image_id_images FOREIGN KEY (image_id) REFERENCES public.images(id) ON DELETE CASCADE;


--
-- Name: detections fk_detections_model_run_id_model_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT fk_detections_model_run_id_model_runs FOREIGN KEY (model_run_id) REFERENCES public.model_runs(id);


--
-- Name: detections fk_detections_species_id_species; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT fk_detections_species_id_species FOREIGN KEY (species_id) REFERENCES public.species(id);


--
-- Name: env_snapshots fk_env_snapshots_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.env_snapshots
    ADD CONSTRAINT fk_env_snapshots_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: forecast_outcomes fk_forecast_outcomes_forecast_id_forecasts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_outcomes
    ADD CONSTRAINT fk_forecast_outcomes_forecast_id_forecasts FOREIGN KEY (forecast_id) REFERENCES public.forecasts(id) ON DELETE CASCADE;


--
-- Name: forecasts fk_forecasts_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT fk_forecasts_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: forecasts fk_forecasts_individual_id_individuals; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT fk_forecasts_individual_id_individuals FOREIGN KEY (individual_id) REFERENCES public.individuals(id);


--
-- Name: forecasts fk_forecasts_model_run_id_model_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT fk_forecasts_model_run_id_model_runs FOREIGN KEY (model_run_id) REFERENCES public.model_runs(id);


--
-- Name: forecasts fk_forecasts_species_id_species; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT fk_forecasts_species_id_species FOREIGN KEY (species_id) REFERENCES public.species(id);


--
-- Name: forecasts fk_forecasts_stand_id_stands; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT fk_forecasts_stand_id_stands FOREIGN KEY (stand_id) REFERENCES public.stands(id);


--
-- Name: harvests fk_harvests_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT fk_harvests_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: harvests fk_harvests_sit_id_sits; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT fk_harvests_sit_id_sits FOREIGN KEY (sit_id) REFERENCES public.sits(id) ON DELETE SET NULL;


--
-- Name: harvests fk_harvests_species_id_species; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT fk_harvests_species_id_species FOREIGN KEY (species_id) REFERENCES public.species(id);


--
-- Name: harvests fk_harvests_stand_id_stands; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT fk_harvests_stand_id_stands FOREIGN KEY (stand_id) REFERENCES public.stands(id) ON DELETE SET NULL;


--
-- Name: harvests fk_harvests_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.harvests
    ADD CONSTRAINT fk_harvests_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: images fk_images_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.images
    ADD CONSTRAINT fk_images_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: individuals fk_individuals_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.individuals
    ADD CONSTRAINT fk_individuals_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: individuals fk_individuals_species_id_species; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.individuals
    ADD CONSTRAINT fk_individuals_species_id_species FOREIGN KEY (species_id) REFERENCES public.species(id);


--
-- Name: notification_prefs fk_notification_prefs_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_prefs
    ADD CONSTRAINT fk_notification_prefs_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notifications fk_notifications_image_id_images; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_image_id_images FOREIGN KEY (image_id) REFERENCES public.images(id) ON DELETE SET NULL;


--
-- Name: notifications fk_notifications_species_id_species; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_species_id_species FOREIGN KEY (species_id) REFERENCES public.species(id);


--
-- Name: notifications fk_notifications_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT fk_notifications_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: photo_notes fk_photo_notes_image_id_images; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photo_notes
    ADD CONSTRAINT fk_photo_notes_image_id_images FOREIGN KEY (image_id) REFERENCES public.images(id) ON DELETE CASCADE;


--
-- Name: photo_notes fk_photo_notes_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.photo_notes
    ADD CONSTRAINT fk_photo_notes_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: push_subscriptions fk_push_subscriptions_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT fk_push_subscriptions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sits fk_sits_stand_id_stands; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sits
    ADD CONSTRAINT fk_sits_stand_id_stands FOREIGN KEY (stand_id) REFERENCES public.stands(id);


--
-- Name: sits fk_sits_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sits
    ADD CONSTRAINT fk_sits_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: stands fk_stands_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stands
    ADD CONSTRAINT fk_stands_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: stands fk_stands_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stands
    ADD CONSTRAINT fk_stands_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: sync_log fk_sync_log_camera_id_cameras; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sync_log
    ADD CONSTRAINT fk_sync_log_camera_id_cameras FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: users fk_users_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- Name: zones fk_zones_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT fk_zones_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: zones fk_zones_estate_id_estates; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT fk_zones_estate_id_estates FOREIGN KEY (estate_id) REFERENCES public.estates(id);


--
-- PostgreSQL database dump complete
--

INSERT INTO public.alembic_version VALUES ('0030_harvest_and_people');
