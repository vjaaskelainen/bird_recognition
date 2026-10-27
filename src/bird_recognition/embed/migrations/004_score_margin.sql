ALTER TABLE bird_embed.species_decision
    DROP CONSTRAINT species_decision_reason_check,
    DROP CONSTRAINT species_decision_check,
    ADD CONSTRAINT species_decision_reason_check
        CHECK (reason IN (
            'assigned', 'below_threshold', 'below_margin', 'exact_tie',
            'low_quality', 'reference_match'
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
            reason IN ('below_threshold', 'below_margin')
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
    );
