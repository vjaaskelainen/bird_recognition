CREATE TABLE bird_embed.video_review (
    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id text NOT NULL CHECK (source_id <> ''),
    outcome text NOT NULL CHECK (outcome IN ('confirmed', 'corrected')),
    correction_kind text CHECK (
        correction_kind IN ('no_animal', 'animal_missed', 'species_present')
    ),
    species jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(species) = 'array'),
    missed_times jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(missed_times) = 'array'
    ),
    note text CHECK (note IS NULL OR char_length(note) <= 2000),
    auto_result jsonb NOT NULL CHECK (jsonb_typeof(auto_result) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    bulk_id uuid,
    CHECK (
        (outcome = 'confirmed' AND correction_kind IS NULL)
        OR (outcome = 'corrected' AND correction_kind IS NOT NULL)
    ),
    CHECK (
        (correction_kind = 'species_present'
         AND jsonb_array_length(species) > 0)
        OR (correction_kind IS DISTINCT FROM 'species_present'
            AND jsonb_array_length(species) = 0)
    ),
    CHECK (
        (correction_kind = 'animal_missed'
         AND jsonb_array_length(missed_times) > 0)
        OR (correction_kind IS DISTINCT FROM 'animal_missed'
            AND jsonb_array_length(missed_times) = 0)
    )
);

CREATE INDEX video_review_source_idx
    ON bird_embed.video_review (source_id, created_at DESC);

CREATE TABLE bird_embed.video_review_undo (
    review_id uuid PRIMARY KEY
        REFERENCES bird_embed.video_review (review_id),
    undone_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bird_embed.crop_correction (
    correction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    crop_id text NOT NULL CHECK (crop_id <> ''),
    source_id text NOT NULL CHECK (source_id <> ''),
    truth_kind text NOT NULL CHECK (
        truth_kind IN ('species', 'out_of_list', 'unidentifiable')
    ),
    species_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (truth_kind = 'species' AND species_id IS NOT NULL AND species_id <> '')
        OR (truth_kind <> 'species' AND species_id IS NULL)
    )
);

CREATE INDEX crop_correction_crop_idx
    ON bird_embed.crop_correction (crop_id, created_at DESC);

CREATE INDEX crop_correction_source_idx
    ON bird_embed.crop_correction (source_id);

CREATE TABLE bird_embed.crop_correction_undo (
    correction_id uuid PRIMARY KEY
        REFERENCES bird_embed.crop_correction (correction_id),
    undone_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION bird_embed.reject_review_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'review records are append-only';
END;
$$;

CREATE TRIGGER video_review_append_only
    BEFORE UPDATE OR DELETE ON bird_embed.video_review
    FOR EACH ROW EXECUTE FUNCTION bird_embed.reject_review_modification();

CREATE TRIGGER video_review_undo_append_only
    BEFORE UPDATE OR DELETE ON bird_embed.video_review_undo
    FOR EACH ROW EXECUTE FUNCTION bird_embed.reject_review_modification();

CREATE TRIGGER crop_correction_append_only
    BEFORE UPDATE OR DELETE ON bird_embed.crop_correction
    FOR EACH ROW EXECUTE FUNCTION bird_embed.reject_review_modification();

CREATE TRIGGER crop_correction_undo_append_only
    BEFORE UPDATE OR DELETE ON bird_embed.crop_correction_undo
    FOR EACH ROW EXECUTE FUNCTION bird_embed.reject_review_modification();
