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
