from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from bird_recognition.embed.models import SearchContextError
from bird_recognition.embed.storage import PgVectorStore, initialize_database


@pytest.mark.real_database
def test_search_storage_preflights_read_only_and_rejects_missing_run(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    store = PgVectorStore(disposable_embed_schema)

    store.preflight(read_only=True)
    with pytest.raises(SearchContextError, match="run selection was not found"):
        store.load_search_collection(uuid4())


@pytest.mark.real_database
def test_search_storage_loads_only_compatible_selected_run_rows_read_only(
    disposable_embed_schema: str,
    tmp_path: Path,
) -> None:
    initialize_database(disposable_embed_schema)
    run_id = uuid4()
    representation_id = uuid4()
    decision_id = uuid4()
    now = datetime.now(UTC)
    model_fingerprint = "a" * 64
    candidate_fingerprint = "b" * 64
    config_fingerprint = "c" * 64
    snapshot_id = "d" * 64
    crop_id = "crop-search-boundary"
    with psycopg.connect(disposable_embed_schema) as connection:
        register_vector(connection)
        connection.execute(
            "INSERT INTO bird_embed.embedding_model "
            "(model_fingerprint,upstream_name,upstream_revision,checkpoint_sha256,"
            "config_sha256,tokenizer_sha256,architecture,dimension,preprocessing_json,"
            "tokenizer_json,adapter_version,runtime_json,logit_scale,canonical_json) "
            "VALUES (%s,'test','revision',%s,%s,%s,'ViT-B-16',512,'{}','{}','test',"
            "'{}',1,%s)",
            (
                model_fingerprint,
                "1" * 64,
                "2" * 64,
                "3" * 64,
                Jsonb({"preprocessing": {"input_view": {"version": "fit-pad-v1"}}}),
            ),
        )
        connection.execute(
            "INSERT INTO bird_embed.candidate_set "
            "(candidate_set_fingerprint,schema_version,candidates_json,canonical_json) "
            "VALUES (%s,1,%s,%s)",
            (
                candidate_fingerprint,
                Jsonb([{"id": "crow", "name": "Crow"}]),
                Jsonb({}),
            ),
        )
        connection.execute(
            "INSERT INTO bird_embed.tagging_config "
            "(config_fingerprint,model_fingerprint,candidate_set_fingerprint,"
            "scoring_fingerprint,prompt_template,prompt_version,effective_logit_scale,"
            "scoring_json,threshold,canonical_json) VALUES "
            "(%s,%s,%s,%s,'a photo of {name}.','species-photo-v1',1,'{}',0.5,'{}')",
            (config_fingerprint, model_fingerprint, candidate_fingerprint, "e" * 64),
        )
        connection.execute(
            "INSERT INTO bird_embed.processing_run "
            "(run_id,started_at,completed_at,status,config_fingerprint,manifest_locator,"
            "selection_fingerprint,selected_count,completed_count,skipped_count,"
            "failed_count,assigned_count,unknown_count,failures_json,"
            "sanitized_settings_json) "
            "VALUES (%s,%s,%s,'complete',%s,'manifest',%s,1,1,0,0,0,1,'[]','{}')",
            (run_id, now, now, config_fingerprint, "f" * 64),
        )
        connection.execute(
            "INSERT INTO bird_embed.crop_snapshot "
            "(snapshot_id,crop_id,provenance_sha256,crop_sha256,source_id,"
            "source_content_sha256,source_original_path,source_basename,"
            "ingest_settings_fingerprint,ingestion_run_id,frame_number,elapsed_seconds,"
            "detection_id,detection_category,detection_confidence,"
            "detection_box_normalized,crop_box_pixels,frame_width,frame_height,"
            "crop_original_image_path,lighting,imported_at) "
            "VALUES (%s,%s,%s,%s,'source-1',%s,'recording.mp4','recording.mp4',"
            "%s,'ingest-run',10,5,'detection-1','animal',0.9,'[0.1,0.2,0.5,0.6]',"
            "'[10,20,50,60]',100,100,'crops/crop.jpg','unknown',%s)",
            (
                snapshot_id,
                crop_id,
                "4" * 64,
                "5" * 64,
                "6" * 64,
                "7" * 64,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO bird_embed.crop_representation "
            "(representation_id,snapshot_id,model_fingerprint,embedding,processed_at,"
            "created_run_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                representation_id,
                snapshot_id,
                model_fingerprint,
                Vector([1.0] + [0.0] * 511),
                now,
                run_id,
            ),
        )
        connection.execute(
            "INSERT INTO bird_embed.species_decision "
            "(decision_id,representation_id,config_fingerprint,assigned_species_id,"
            "best_candidate_id,confidence,tied_candidate_ids,candidate_scores_json,"
            "reason,warnings_json,processed_at,created_run_id) "
            "VALUES (%s,%s,%s,NULL,'crow',0.4,'[]',%s,'below_threshold','[]',%s,%s)",
            (
                decision_id,
                representation_id,
                config_fingerprint,
                Jsonb([{"id": "crow", "logit": 0.1, "score": 1.0}]),
                now,
                run_id,
            ),
        )
        connection.execute(
            "INSERT INTO bird_embed.run_item "
            "(run_id,crop_id,expected_snapshot_id,expected_provenance_sha256,"
            "resolved_input_locator,status,decision_id,started_at,completed_at,"
            "lighting) "
            "VALUES (%s,%s,%s,%s,%s,'completed',%s,%s,%s,'unknown')",
            (
                run_id,
                crop_id,
                snapshot_id,
                "4" * 64,
                str(tmp_path / "missing-crop.jpg"),
                decision_id,
                now,
                now,
            ),
        )

    store = PgVectorStore(disposable_embed_schema)
    store.preflight(read_only=True)
    context, candidates = store.load_search_collection(run_id)
    with psycopg.connect(disposable_embed_schema) as connection:
        persisted_count = connection.execute(
            "SELECT count(*) FROM bird_embed.run_item WHERE run_id=%s", (run_id,)
        ).fetchone()[0]

    assert context.run_id == run_id
    assert context.model_fingerprint == model_fingerprint
    assert context.config_fingerprint == config_fingerprint
    assert context.selected_crop_ids == (crop_id,)
    assert len(candidates) == 1
    assert candidates[0].result.representation_id == representation_id
    assert candidates[0].embedding[0] == pytest.approx(1.0)
    assert persisted_count == 1
