from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from bird_recognition.embed.models import Lighting, SearchContextError, SearchRequest
from bird_recognition.embed.storage import PgVectorStore, initialize_database


@pytest.mark.real_database
def test_search_storage_preflights_read_only_and_rejects_missing_run(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    store = PgVectorStore(disposable_embed_schema)

    store.preflight(read_only=True)
    with pytest.raises(SearchContextError, match="run selection was not found"):
        store.load_search_collection(SearchRequest(query="owl", run_id=uuid4()))


@pytest.mark.real_database
def test_search_storage_loads_only_compatible_selected_run_rows_read_only(
    disposable_embed_schema: str,
    tmp_path: Path,
) -> None:
    initialize_database(disposable_embed_schema)
    run_id = uuid4()
    now = datetime.now(UTC)
    model_fingerprint = "a" * 64
    candidate_fingerprint = "b" * 64
    config_fingerprint = "c" * 64
    crop_records = (
        (
            "a-unassigned-best-candidate",
            "1" * 64,
            uuid4(),
            uuid4(),
            None,
            "crow",
            "2026-10-25T12:00:00",
            "day",
            "day",
        ),
        (
            "b-assigned-wrong-lighting",
            "2" * 64,
            uuid4(),
            uuid4(),
            "crow",
            "crow",
            "2026-10-25T12:00:00",
            "night",
            "night",
        ),
        (
            "z-eligible-filtered-result",
            "3" * 64,
            uuid4(),
            uuid4(),
            "crow",
            "crow",
            "2026-10-25T12:00:00",
            "day",
            "day",
        ),
    )
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
            "VALUES (%s,%s,%s,'complete',%s,'manifest',%s,3,3,0,0,2,1,'[]','{}')",
            (run_id, now, now, config_fingerprint, "f" * 64),
        )
        for index, record in enumerate(crop_records, start=4):
            (
                crop_id,
                snapshot_id,
                representation_id,
                decision_id,
                assigned_id,
                best_id,
                capture_time,
                snapshot_lighting,
                item_lighting,
            ) = record
            connection.execute(
                "INSERT INTO bird_embed.crop_snapshot "
                "(snapshot_id,crop_id,provenance_sha256,crop_sha256,source_id,"
                "source_content_sha256,source_original_path,source_basename,"
                "ingest_settings_fingerprint,ingestion_run_id,frame_number,elapsed_seconds,"
                "detection_id,detection_category,detection_confidence,"
                "detection_box_normalized,crop_box_pixels,frame_width,frame_height,"
                "crop_original_image_path,capture_time,lighting,imported_at) "
                "VALUES (%s,%s,%s,%s,'source-1',%s,'recording.mp4','recording.mp4',"
                "%s,'ingest-run',10,5,'detection-1','animal',0.9,'[0.1,0.2,0.5,0.6]',"
                "'[10,20,50,60]',100,100,'crops/crop.jpg',%s,%s,%s)",
                (
                    snapshot_id,
                    crop_id,
                    f"{index}" * 64,
                    f"{index + 1}" * 64,
                    "6" * 64,
                    "7" * 64,
                    capture_time,
                    snapshot_lighting,
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
                "VALUES (%s,%s,%s,%s,%s,0.4,'[]',%s,%s,'[]',%s,%s)",
                (
                    decision_id,
                    representation_id,
                    config_fingerprint,
                    assigned_id,
                    best_id,
                    Jsonb([{"id": "crow", "logit": 0.1, "score": 1.0}]),
                    "assigned" if assigned_id else "below_threshold",
                    now,
                    run_id,
                ),
            )
            connection.execute(
                "INSERT INTO bird_embed.run_item "
                "(run_id,crop_id,expected_snapshot_id,expected_provenance_sha256,"
                "resolved_input_locator,status,decision_id,started_at,completed_at,"
                "lighting) VALUES (%s,%s,%s,%s,%s,'completed',%s,%s,%s,%s)",
                (
                    run_id,
                    crop_id,
                    snapshot_id,
                    f"{index}" * 64,
                    str(tmp_path / f"{crop_id}.jpg"),
                    decision_id,
                    now,
                    now,
                    item_lighting,
                ),
            )

    store = PgVectorStore(disposable_embed_schema)
    store.preflight(read_only=True)
    request = SearchRequest(
        query="crow at night on October 25",
        run_id=run_id,
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 25),
        lighting=Lighting.DAY,
        species_id="crow",
        limit=1,
    )
    context, candidates = store.load_search_collection(request)
    with psycopg.connect(disposable_embed_schema) as connection:
        persisted_count = connection.execute(
            "SELECT count(*) FROM bird_embed.run_item WHERE run_id=%s", (run_id,)
        ).fetchone()[0]

    assert context.run_id == run_id
    assert context.model_fingerprint == model_fingerprint
    assert context.config_fingerprint == config_fingerprint
    assert context.selected_crop_ids == tuple(record[0] for record in crop_records)
    assert len(candidates) == 1
    assert candidates[0].result.crop_id == "z-eligible-filtered-result"
    assert candidates[0].result.assigned_species_id == "crow"
    assert candidates[0].embedding[0] == pytest.approx(1.0)
    assert persisted_count == 3
