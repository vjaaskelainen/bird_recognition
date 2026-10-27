ALTER TABLE bird_embed.candidate_set
    DROP CONSTRAINT candidate_set_schema_version_check,
    ADD CONSTRAINT candidate_set_schema_version_check
        CHECK (schema_version IN (1, 2));

ALTER TABLE bird_embed.tagging_config
    DROP CONSTRAINT tagging_config_prompt_template_check,
    DROP CONSTRAINT tagging_config_prompt_version_check,
    ADD CONSTRAINT tagging_config_prompt_identity_check
        CHECK (
            (prompt_template = 'a photo of {name}.'
             AND prompt_version = 'species-photo-v1')
            OR
            (prompt_template = 'a photo of {common_name} ({taxonomic_description}).'
             AND prompt_version = 'species-taxonomy-photo-v2')
        );

ALTER TABLE bird_embed.species_decision
    DROP CONSTRAINT species_decision_reason_check,
    DROP CONSTRAINT species_decision_candidate_scores_json_check,
    DROP CONSTRAINT species_decision_check,
    ALTER COLUMN confidence DROP NOT NULL,
    ADD CONSTRAINT species_decision_reason_check
        CHECK (reason IN ('assigned', 'below_threshold', 'exact_tie', 'low_quality')),
    ADD CONSTRAINT species_decision_candidate_scores_json_check CHECK (
        jsonb_typeof(candidate_scores_json) = 'array'
        AND (
            (reason = 'low_quality' AND jsonb_array_length(candidate_scores_json) = 0)
            OR
            (reason <> 'low_quality' AND jsonb_array_length(candidate_scores_json) > 0)
        )
    ),
    ADD CONSTRAINT species_decision_check CHECK (
        (
            reason = 'exact_tie'
            AND assigned_species_id IS NULL
            AND best_candidate_id IS NULL
            AND confidence IS NOT NULL
            AND jsonb_array_length(tied_candidate_ids) >= 2
        )
        OR
        (
            reason = 'below_threshold'
            AND assigned_species_id IS NULL
            AND best_candidate_id IS NOT NULL
            AND confidence IS NOT NULL
            AND jsonb_array_length(tied_candidate_ids) = 0
        )
        OR
        (
            reason = 'assigned'
            AND assigned_species_id = best_candidate_id
            AND best_candidate_id IS NOT NULL
            AND confidence IS NOT NULL
            AND jsonb_array_length(tied_candidate_ids) = 0
        )
        OR
        (
            reason = 'low_quality'
            AND assigned_species_id IS NULL
            AND best_candidate_id IS NULL
            AND confidence IS NULL
            AND jsonb_array_length(tied_candidate_ids) = 0
        )
    );

