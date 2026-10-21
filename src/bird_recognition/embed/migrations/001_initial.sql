SET TIME ZONE 'UTC';

CREATE SCHEMA bird_embed;

CREATE TABLE bird_embed.schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version > 0),
    installed_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO bird_embed.schema_version (singleton, version) VALUES (true, 1);

CREATE TABLE bird_embed.embedding_model (
    model_fingerprint char(64) PRIMARY KEY,
    upstream_name text NOT NULL,
    upstream_revision text NOT NULL,
    checkpoint_sha256 char(64) NOT NULL,
    config_sha256 char(64) NOT NULL,
    tokenizer_sha256 char(64) NOT NULL,
    architecture text NOT NULL CHECK (architecture = 'ViT-B-16'),
    dimension integer NOT NULL CHECK (dimension = 512),
    preprocessing_json jsonb NOT NULL,
    tokenizer_json jsonb NOT NULL,
    adapter_version text NOT NULL,
    runtime_json jsonb NOT NULL,
    logit_scale double precision NOT NULL CHECK (
        logit_scale > 0
        AND logit_scale < 'Infinity'::double precision
        AND logit_scale <> 'NaN'::double precision
    ),
    canonical_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bird_embed.candidate_set (
    candidate_set_fingerprint char(64) PRIMARY KEY,
    schema_version integer NOT NULL CHECK (schema_version = 1),
    candidates_json jsonb NOT NULL CHECK (
        jsonb_typeof(candidates_json) = 'array'
        AND jsonb_array_length(candidates_json) > 0
    ),
    canonical_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bird_embed.tagging_config (
    config_fingerprint char(64) PRIMARY KEY,
    model_fingerprint char(64) NOT NULL REFERENCES bird_embed.embedding_model,
    candidate_set_fingerprint char(64) NOT NULL
        REFERENCES bird_embed.candidate_set,
    scoring_fingerprint char(64) NOT NULL,
    prompt_template text NOT NULL CHECK (prompt_template = 'a photo of {name}.'),
    prompt_version text NOT NULL CHECK (prompt_version = 'species-photo-v1'),
    effective_logit_scale double precision NOT NULL CHECK (
        effective_logit_scale > 0
        AND effective_logit_scale < 'Infinity'::double precision
        AND effective_logit_scale <> 'NaN'::double precision
    ),
    scoring_json jsonb NOT NULL,
    threshold double precision NOT NULL CHECK (
        threshold >= 0 AND threshold <= 1 AND threshold <> 'NaN'::double precision
    ),
    canonical_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bird_embed.crop_snapshot (
    snapshot_id char(64) PRIMARY KEY,
    crop_id text NOT NULL,
    provenance_sha256 char(64) NOT NULL,
    crop_sha256 char(64) NOT NULL,
    source_id text NOT NULL,
    source_content_sha256 char(64) NOT NULL,
    source_original_path text NOT NULL,
    source_basename text NOT NULL,
    ingest_settings_fingerprint char(64) NOT NULL,
    ingestion_run_id text NOT NULL,
    frame_number bigint NOT NULL CHECK (frame_number >= 0),
    elapsed_seconds double precision NOT NULL CHECK (
        elapsed_seconds >= 0
        AND elapsed_seconds < 'Infinity'::double precision
        AND elapsed_seconds <> 'NaN'::double precision
    ),
    detection_id text NOT NULL,
    detection_category text NOT NULL CHECK (detection_category = 'animal'),
    detection_confidence double precision NOT NULL CHECK (
        detection_confidence >= 0
        AND detection_confidence <= 1
        AND detection_confidence <> 'NaN'::double precision
    ),
    detection_box_normalized jsonb NOT NULL CHECK (
        jsonb_typeof(detection_box_normalized) = 'array'
        AND jsonb_array_length(detection_box_normalized) = 4
    ),
    crop_box_pixels jsonb NOT NULL CHECK (
        jsonb_typeof(crop_box_pixels) = 'array'
        AND jsonb_array_length(crop_box_pixels) = 4
    ),
    frame_width integer NOT NULL CHECK (frame_width > 0),
    frame_height integer NOT NULL CHECK (frame_height > 0),
    crop_original_image_path text NOT NULL,
    capture_time text,
    capture_timezone text,
    source_capture_start text,
    source_capture_timezone text,
    lighting text NOT NULL CHECK (lighting IN ('day', 'night', 'unknown')),
    imported_at timestamptz NOT NULL,
    UNIQUE (crop_id, provenance_sha256)
);

CREATE TABLE bird_embed.processing_run (
    run_id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL CHECK (
        status IN ('running', 'complete', 'no_input', 'partial_failure', 'failed', 'interrupted')
    ),
    config_fingerprint char(64) NOT NULL REFERENCES bird_embed.tagging_config,
    manifest_locator text NOT NULL,
    crop_root text,
    selection_fingerprint char(64) NOT NULL,
    selected_count integer NOT NULL CHECK (selected_count >= 0),
    completed_count integer NOT NULL CHECK (completed_count >= 0),
    skipped_count integer NOT NULL CHECK (skipped_count >= 0),
    failed_count integer NOT NULL CHECK (failed_count >= 0),
    assigned_count integer NOT NULL CHECK (assigned_count >= 0),
    unknown_count integer NOT NULL CHECK (unknown_count >= 0),
    failures_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    sanitized_settings_json jsonb NOT NULL,
    CHECK (assigned_count + unknown_count = completed_count),
    CHECK (completed_count + skipped_count + failed_count <= selected_count),
    CHECK (status NOT IN ('complete', 'no_input', 'partial_failure') OR
           completed_count + skipped_count + failed_count = selected_count),
    CHECK (status <> 'no_input' OR selected_count = 0)
);

CREATE TABLE bird_embed.crop_representation (
    representation_id uuid PRIMARY KEY,
    snapshot_id char(64) NOT NULL REFERENCES bird_embed.crop_snapshot,
    model_fingerprint char(64) NOT NULL REFERENCES bird_embed.embedding_model,
    embedding vector(512) NOT NULL CHECK (
        embedding::text !~ '(NaN|Infinity)'
        AND vector_norm(embedding) > 0
        AND abs(vector_norm(embedding) - 1.0) <= 1e-5
    ),
    processed_at timestamptz NOT NULL,
    created_run_id uuid NOT NULL REFERENCES bird_embed.processing_run,
    UNIQUE (snapshot_id, model_fingerprint)
);

CREATE TABLE bird_embed.species_decision (
    decision_id uuid PRIMARY KEY,
    representation_id uuid NOT NULL REFERENCES bird_embed.crop_representation,
    config_fingerprint char(64) NOT NULL REFERENCES bird_embed.tagging_config,
    assigned_species_id text,
    best_candidate_id text,
    confidence double precision NOT NULL CHECK (
        confidence >= 0
        AND confidence <= 1
        AND confidence <> 'NaN'::double precision
    ),
    tied_candidate_ids jsonb NOT NULL CHECK (jsonb_typeof(tied_candidate_ids) = 'array'),
    candidate_scores_json jsonb NOT NULL CHECK (
        jsonb_typeof(candidate_scores_json) = 'array'
        AND jsonb_array_length(candidate_scores_json) > 0
    ),
    reason text NOT NULL CHECK (reason IN ('assigned', 'below_threshold', 'exact_tie')),
    warnings_json jsonb NOT NULL CHECK (jsonb_typeof(warnings_json) = 'array'),
    processed_at timestamptz NOT NULL,
    created_run_id uuid NOT NULL REFERENCES bird_embed.processing_run,
    CHECK (
        (reason = 'exact_tie' AND assigned_species_id IS NULL
         AND best_candidate_id IS NULL AND jsonb_array_length(tied_candidate_ids) >= 2)
        OR
        (reason = 'below_threshold' AND assigned_species_id IS NULL
         AND best_candidate_id IS NOT NULL AND jsonb_array_length(tied_candidate_ids) = 0)
        OR
        (reason = 'assigned' AND assigned_species_id = best_candidate_id
         AND best_candidate_id IS NOT NULL
         AND jsonb_array_length(tied_candidate_ids) = 0)
    ),
    UNIQUE (representation_id, config_fingerprint)
);

CREATE TABLE bird_embed.run_item (
    run_id uuid NOT NULL REFERENCES bird_embed.processing_run,
    crop_id text NOT NULL,
    expected_snapshot_id char(64),
    expected_provenance_sha256 char(64) NOT NULL,
    resolved_input_locator text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'completed', 'skipped', 'failed')),
    decision_id uuid REFERENCES bird_embed.species_decision,
    failure_code text,
    failure_reason text,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    CHECK (
        (status IN ('completed', 'skipped') AND decision_id IS NOT NULL
         AND failure_code IS NULL AND failure_reason IS NULL)
        OR
        (status = 'failed' AND decision_id IS NULL
         AND failure_code IS NOT NULL AND failure_reason IS NOT NULL)
        OR
        (status = 'pending' AND decision_id IS NULL
         AND failure_code IS NULL AND failure_reason IS NULL)
    ),
    PRIMARY KEY (run_id, crop_id)
);

CREATE INDEX run_item_decision_id_idx ON bird_embed.run_item (decision_id);

