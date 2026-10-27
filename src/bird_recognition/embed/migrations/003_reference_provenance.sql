ALTER TABLE bird_embed.species_decision
    DROP CONSTRAINT species_decision_reason_check,
    DROP CONSTRAINT species_decision_check,
    ADD CONSTRAINT species_decision_reason_check
        CHECK (reason IN (
            'assigned', 'below_threshold', 'exact_tie', 'low_quality',
            'reference_match'
        )),
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
        OR
        (
            reason = 'reference_match'
            AND assigned_species_id IS NOT NULL
            AND confidence IS NOT NULL
            AND (
                (best_candidate_id IS NULL
                 AND jsonb_array_length(tied_candidate_ids) >= 2)
                OR
                (best_candidate_id IS NOT NULL
                 AND jsonb_array_length(tied_candidate_ids) = 0)
            )
        )
    ),
    ADD COLUMN decision_path text NOT NULL DEFAULT 'zero_shot',
    ADD COLUMN reference_set_fingerprint char(64),
    ADD COLUMN reference_split_mode text,
    ADD COLUMN reference_similarity double precision,
    ADD COLUMN reference_agreement double precision,
    ADD COLUMN reference_neighbor_ids jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE bird_embed.species_decision
    ADD CONSTRAINT species_decision_path_check CHECK (
        decision_path IN ('zero_shot', 'reference_match', 'zero_shot_fallback')
    ),
    ADD CONSTRAINT species_decision_reference_provenance_check CHECK (
        (
            decision_path = 'zero_shot'
            AND reference_set_fingerprint IS NULL
            AND reference_split_mode IS NULL
            AND reference_similarity IS NULL
            AND reference_agreement IS NULL
            AND reference_neighbor_ids = '[]'::jsonb
        )
        OR
        (
            decision_path IN ('reference_match', 'zero_shot_fallback')
            AND reference_set_fingerprint IS NOT NULL
            AND reference_split_mode IN ('source_video', 'recording_day')
            AND jsonb_typeof(reference_neighbor_ids) = 'array'
            AND (reference_similarity IS NULL OR (
                reference_similarity >= -1
                AND reference_similarity <= 1
                AND reference_similarity <> 'NaN'::double precision
            ))
            AND (reference_agreement IS NULL OR (
                reference_agreement >= 0
                AND reference_agreement <= 1
                AND reference_agreement <> 'NaN'::double precision
            ))
            AND (
                (decision_path = 'reference_match' AND reason = 'reference_match'
                 AND assigned_species_id IS NOT NULL)
                OR
                (decision_path = 'zero_shot_fallback' AND reason <> 'reference_match')
            )
        )
    );

