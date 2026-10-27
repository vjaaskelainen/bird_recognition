"""Preflight and sequential crop-indexing orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from bird_recognition.embed.config import (
    build_tagging_config,
    canonical_json_sha256,
    format_candidate_prompt,
    load_species_candidates,
    validate_minimum_crop_dimensions,
    validate_threshold,
)
from bird_recognition.embed.manifest import read_manifest_snapshot, resolve_crop_path
from bird_recognition.embed.models import (
    CropRepresentation,
    EmbeddingModelRecord,
    EmbedValidationError,
    IngestedCropSnapshot,
    IsolatedCropError,
    ModelProtocol,
    PreflightError,
    ProcessingRun,
    RunFailure,
    RunItem,
    RunItemStatus,
    RunStatus,
    SharedModelError,
    SpeciesCandidateSet,
    SpeciesDecision,
    StorageError,
    StoreProtocol,
    TaggingConfig,
    UnconfirmedCommitError,
)
from bird_recognition.embed.reference import (
    ReferenceMatch,
    ReferenceSet,
    encode_reference_examples,
    input_view_fingerprint,
    load_reference_manifest,
    match_reference,
    validate_reference_split,
)
from bird_recognition.embed.scoring import (
    ScoreResult,
    decision_from_score_map,
    score_embeddings,
    validate_normalized_vector,
)

_FAILURE_MESSAGES = {
    "crop_hash_mismatch": "crop bytes do not match their manifest digest",
    "crop_read_error": "crop could not be read",
    "crop_decode_error": "crop image could not be decoded",
    "invalid_vector": "model returned an invalid image vector",
    "invalid_scores": "model returned invalid candidate scores",
    "inference_error": "crop inference failed",
}


def index_manifest(
    manifest_path: Path,
    *,
    crop_root: Path | None,
    species_path: Path,
    model_directory: Path,
    threshold: object,
    store: StoreProtocol,
    input_view: str = "fit-pad-v1",
    minimum_crop_width: int = 32,
    minimum_crop_height: int = 32,
    reference_manifest: Path | None = None,
    reference_split_mode: str = "source_video",
    reference_min_similarity: object = None,
    reference_min_agreement: object = None,
) -> ProcessingRun:
    """Validate all inputs and run indexing against the read-only manifest snapshot."""
    from bird_recognition.embed.bioclip import load_bioclip

    if reference_manifest is None and (
        reference_split_mode != "source_video"
        or reference_min_similarity is not None
        or reference_min_agreement is not None
    ):
        raise EmbedValidationError("reference options require --reference-set")
    if reference_manifest is not None and (
        reference_min_similarity is None or reference_min_agreement is None
    ):
        raise EmbedValidationError(
            "reference mode requires both minimum similarity and agreement"
        )
    try:
        manifest = Path(manifest_path).expanduser().resolve(strict=True)
        effective_crop_root = (
            Path(crop_root).expanduser().resolve(strict=True)
            if crop_root is not None
            else manifest.parent
        )
    except OSError:
        raise EmbedValidationError(
            "manifest or relocated crop root is unavailable"
        ) from None
    snapshots = read_manifest_snapshot(manifest, effective_crop_root)
    candidates = load_species_candidates(Path(species_path).expanduser())
    validated_threshold = validate_threshold(threshold)
    minimum_crop_width, minimum_crop_height = validate_minimum_crop_dimensions(
        minimum_crop_width, minimum_crop_height
    )
    model = load_bioclip(Path(model_directory).expanduser(), input_view=input_view)
    reference_set: ReferenceSet | None = None
    if reference_manifest is not None:
        reference_set = load_reference_manifest(
            reference_manifest,
            model_fingerprint=model.identity.model_fingerprint,
            input_view_fingerprint=input_view_fingerprint(model),
        )
        validate_reference_split(
            reference_set,
            [
                {
                    "crop_id": snapshot.crop_id,
                    "source_id": snapshot.source_id,
                    "capture_time": snapshot.capture_time,
                    "source_capture_start": snapshot.source_capture_start,
                }
                for snapshot in snapshots
            ],
            split_mode=reference_split_mode,
        )
        species_ids = {
            candidate.id
            for candidate in candidates.candidates
            if candidate.kind == "species"
        }
        if any(
            example.species_id not in species_ids for example in reference_set.examples
        ):
            raise EmbedValidationError(
                "reference species must be present as a species candidate"
            )
    config = build_tagging_config(
        model.identity,
        candidates,
        validated_threshold,
        minimum_crop_width=minimum_crop_width,
        minimum_crop_height=minimum_crop_height,
        reference_set_fingerprint=(
            reference_set.fingerprint if reference_set is not None else None
        ),
        reference_split_mode=(
            reference_split_mode if reference_set is not None else None
        ),
        reference_min_similarity=reference_min_similarity,
        reference_min_agreement=reference_min_agreement,
    )
    if reference_set is not None:
        reference_set = encode_reference_examples(reference_set, model)
    return index_crops(
        snapshots,
        crop_root=effective_crop_root,
        manifest_locator=manifest,
        candidates=candidates,
        model=model,
        store=store,
        threshold=validated_threshold,
        config=config,
        reference_set=reference_set,
    )


def index_crops(
    snapshots: list[IngestedCropSnapshot] | tuple[IngestedCropSnapshot, ...],
    *,
    crop_root: Path,
    manifest_locator: Path,
    candidates: SpeciesCandidateSet,
    model: ModelProtocol,
    store: StoreProtocol,
    threshold: object = 0.5,
    config: TaggingConfig | None = None,
    minimum_crop_width: int = 32,
    minimum_crop_height: int = 32,
    reference_set: ReferenceSet | None = None,
    reference_split_mode: str = "source_video",
    reference_min_similarity: object = None,
    reference_min_agreement: object = None,
) -> ProcessingRun:
    """Index a stable snapshot list with atomic per-crop commits."""
    validated_threshold = validate_threshold(threshold)
    identity = model.identity
    tagging_config = config or build_tagging_config(
        identity,
        candidates,
        validated_threshold,
        minimum_crop_width=minimum_crop_width,
        minimum_crop_height=minimum_crop_height,
        reference_set_fingerprint=(
            reference_set.fingerprint if reference_set is not None else None
        ),
        reference_split_mode=(
            reference_split_mode if reference_set is not None else None
        ),
        reference_min_similarity=reference_min_similarity,
        reference_min_agreement=reference_min_agreement,
    )
    if tagging_config.model_fingerprint != identity.model_fingerprint:
        raise EmbedValidationError("tagging config does not match the loaded model")
    if tagging_config.candidate_set_fingerprint != candidates.candidate_set_fingerprint:
        raise EmbedValidationError(
            "tagging config does not match the selected candidates"
        )
    if tagging_config.threshold != validated_threshold:
        raise EmbedValidationError(
            "tagging config does not match the selected threshold"
        )
    if reference_set is not None and (
        tagging_config.reference_set_fingerprint != reference_set.fingerprint
        or tagging_config.reference_split_mode is None
        or reference_set.model_fingerprint != identity.model_fingerprint
        or reference_set.input_view_fingerprint != input_view_fingerprint(model)
    ):
        raise EmbedValidationError("reference set does not match the selected setup")
    if reference_set is None and tagging_config.reference_set_fingerprint is not None:
        raise EmbedValidationError("tagging config requires its reference set")
    if reference_set is not None:
        validate_reference_split(
            reference_set,
            [
                {
                    "crop_id": snapshot.crop_id,
                    "source_id": snapshot.source_id,
                    "capture_time": snapshot.capture_time,
                    "source_capture_start": snapshot.source_capture_start,
                }
                for snapshot in snapshots
            ],
            split_mode=tagging_config.reference_split_mode,
        )
        species_ids = {
            candidate.id
            for candidate in candidates.candidates
            if candidate.kind == "species"
        }
        if any(
            example.species_id not in species_ids for example in reference_set.examples
        ):
            raise EmbedValidationError(
                "reference species must be present as a species candidate"
            )
        if any(
            example.embedding is None
            or len(validate_normalized_vector(example.embedding)) != identity.dimension
            for example in reference_set.examples
        ):
            raise EmbedValidationError(
                "reference embeddings are incomplete or incompatible"
            )

    try:
        store.preflight()
        store.acquire_writer_lock()
    except StorageError as error:
        raise PreflightError(str(error)) from None
    run_result: ProcessingRun | None = None
    try:
        store.recover_stale_runs()
        run_result = _run_index(
            tuple(snapshots),
            crop_root=Path(crop_root),
            manifest_locator=Path(manifest_locator),
            candidates=candidates,
            model=model,
            model_identity=identity,
            store=store,
            config=tagging_config,
            reference_set=reference_set,
        )
    finally:
        try:
            store.release_writer_lock()
        except StorageError:
            if run_result is None or run_result.durable_status_confirmed:
                raise
    if run_result is None:
        raise StorageError("index run did not produce a status")
    return run_result


def _run_index(
    snapshots: tuple[IngestedCropSnapshot, ...],
    *,
    crop_root: Path,
    manifest_locator: Path,
    candidates: SpeciesCandidateSet,
    model: ModelProtocol,
    model_identity: EmbeddingModelRecord,
    store: StoreProtocol,
    config: TaggingConfig,
    reference_set: ReferenceSet | None = None,
) -> ProcessingRun:
    now = datetime.now(UTC)
    run_id = uuid4()
    ordered_snapshots = tuple(sorted(snapshots, key=lambda item: item.crop_id))
    selection = [
        [snapshot.crop_id, snapshot.provenance_sha256] for snapshot in ordered_snapshots
    ]
    run = ProcessingRun(
        run_id=run_id,
        started_at=now,
        completed_at=None,
        status=RunStatus.RUNNING,
        config_fingerprint=config.config_fingerprint,
        manifest_locator=manifest_locator,
        crop_root=crop_root,
        selection_fingerprint=canonical_json_sha256(selection),
        selected_count=len(ordered_snapshots),
        completed_count=0,
        skipped_count=0,
        failed_count=0,
        assigned_count=0,
        unknown_count=0,
        failures=(),
        sanitized_settings_json=json.dumps(
            {
                "threshold": config.threshold,
                "minimum_crop_width": config.minimum_crop_width,
                "minimum_crop_height": config.minimum_crop_height,
                "model_fingerprint": model_identity.model_fingerprint,
                "candidate_set_fingerprint": candidates.candidate_set_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        model_fingerprint=model_identity.model_fingerprint,
        candidate_set_fingerprint=candidates.candidate_set_fingerprint,
        scoring_fingerprint=config.scoring_fingerprint,
        threshold=config.threshold,
        candidate_count=len(candidates.candidates),
        candidate_schema_version=candidates.schema_version,
        prompt_template=config.prompt_template,
        prompt_version=config.prompt_version,
        reference_set_fingerprint=config.reference_set_fingerprint,
        reference_split_mode=config.reference_split_mode,
    )
    pending_items = tuple(
        RunItem(
            run_id=run_id,
            crop_id=snapshot.crop_id,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_provenance_sha256=snapshot.provenance_sha256,
            resolved_input_locator=crop_root / snapshot.crop_original_image_path,
            status=RunItemStatus.PENDING,
            decision_id=None,
            failure_code=None,
            failure_reason=None,
            started_at=now,
            completed_at=None,
            lighting=snapshot.lighting,
        )
        for snapshot in ordered_snapshots
    )
    store.register_run(run, pending_items, model_identity, candidates, config)
    current_items = {item.crop_id: item for item in pending_items}
    failures: list[RunFailure] = []
    completed = 0
    skipped = 0
    failed = 0
    assigned = 0
    unknown = 0
    text_vectors = None
    fatal = False
    unconfirmed_crop_ids: tuple[str, ...] = ()

    if not ordered_snapshots:
        return _finalize(
            store,
            run,
            status=RunStatus.NO_INPUT,
            completed=0,
            skipped=0,
            failed=0,
            assigned=0,
            unknown=0,
            failures=(),
        )

    try:
        for snapshot in ordered_snapshots:
            pending_item = current_items[snapshot.crop_id]
            try:
                crop_path = resolve_crop_path(
                    crop_root, snapshot.crop_original_image_path
                )
                image_bytes = crop_path.read_bytes()
            except (IsolatedCropError, OSError) as error:
                failure = _failure("crop_read_error", snapshot.crop_id, error)
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue

            if hashlib.sha256(image_bytes).hexdigest() != snapshot.crop_sha256:
                failure = RunFailure(
                    snapshot.crop_id,
                    "crop_hash_mismatch",
                    _FAILURE_MESSAGES["crop_hash_mismatch"],
                )
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue

            completed_decision = store.get_completed_decision(
                snapshot.snapshot_id,
                model_identity.model_fingerprint,
                config.config_fingerprint,
            )
            if completed_decision is not None:
                skipped_item = replace(
                    pending_item,
                    status=RunItemStatus.SKIPPED,
                    decision_id=completed_decision.decision_id,
                    completed_at=datetime.now(UTC),
                )
                store.mark_item_skipped(skipped_item)
                skipped += 1
                continue

            compatible_representation = store.get_compatible_representation(
                snapshot.snapshot_id, model_identity.model_fingerprint
            )
            if compatible_representation is not None and (
                compatible_representation.snapshot_id != snapshot.snapshot_id
                or compatible_representation.model_fingerprint
                != model_identity.model_fingerprint
            ):
                raise StorageError("stored representation identity is incompatible")

            try:
                with Image.open(crop_path) as image:
                    image.verify()
                with Image.open(crop_path) as image:
                    crop_width, crop_height = image.size
            except UnidentifiedImageError, OSError:
                failure = RunFailure(
                    snapshot.crop_id,
                    "crop_decode_error",
                    _FAILURE_MESSAGES["crop_decode_error"],
                )
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue
            low_quality = (
                crop_width < config.minimum_crop_width
                or crop_height < config.minimum_crop_height
            )

            image_vector: tuple[float, ...] = ()
            compatible_score_map = (
                store.get_compatible_score_map(
                    compatible_representation.representation_id,
                    config.scoring_fingerprint,
                )
                if compatible_representation is not None and not low_quality
                else None
            )
            try:
                if compatible_score_map is not None:
                    image_vector = validate_normalized_vector(
                        compatible_representation.embedding
                    )
                    result = decision_from_score_map(
                        compatible_score_map,
                        candidates.candidates,
                        threshold=config.threshold,
                    )
                else:
                    if not low_quality and text_vectors is None:
                        prompts = tuple(
                            format_candidate_prompt(item, config.prompt_template)
                            for item in candidates.candidates
                        )
                        try:
                            encoded_texts = model.encode_texts(prompts)
                            text_vectors = tuple(
                                validate_normalized_vector(vector)
                                for vector in encoded_texts
                            )
                        except EmbedValidationError as error:
                            raise SharedModelError(
                                "BioCLIP returned invalid candidate vectors"
                            ) from error
                        if len(text_vectors) != len(candidates.candidates):
                            raise SharedModelError(
                                "BioCLIP returned an incomplete candidate vector set"
                            )
                    if compatible_representation is not None:
                        image_vector = validate_normalized_vector(
                            compatible_representation.embedding
                        )
                    else:
                        with Image.open(crop_path) as image:
                            image.load()
                            image_vector = model.encode_image(image.convert("RGB"))
                        image_vector = validate_normalized_vector(image_vector)
                    if low_quality:
                        result = ScoreResult(
                            assigned_species_id=None,
                            best_candidate_id=None,
                            confidence=None,
                            tied_candidate_ids=(),
                            scores=(),
                            reason="low_quality",
                            warnings=(
                                "Crop is below the configured minimum dimensions; "
                                "candidate scores were not computed.",
                            ),
                        )
                    else:
                        result = score_embeddings(
                            image_vector,
                            text_vectors,
                            candidates.candidates,
                            logit_scale=config.effective_logit_scale,
                            threshold=config.threshold,
                        )
                reference_match: ReferenceMatch | None = None
                if reference_set is not None:
                    reference_match = (
                        ReferenceMatch(
                            None,
                            "zero_shot_fallback",
                            None,
                            (),
                            None,
                        )
                        if low_quality
                        else match_reference(
                            image_vector,
                            reference_set,
                            minimum_similarity=config.reference_min_similarity,
                            minimum_agreement=config.reference_min_agreement,
                        )
                    )
                    if reference_match.decision_path == "reference_match":
                        result = replace(
                            result,
                            assigned_species_id=reference_match.species_id,
                            reason="reference_match",
                        )
            except UnidentifiedImageError, OSError:
                failure = RunFailure(
                    snapshot.crop_id,
                    "crop_decode_error",
                    _FAILURE_MESSAGES["crop_decode_error"],
                )
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue
            except SharedModelError:
                failures.append(
                    RunFailure(
                        None,
                        "model_unavailable",
                        "shared BioCLIP inference failed",
                    )
                )
                fatal = True
                break
            except EmbedValidationError as error:
                code = (
                    "invalid_vector"
                    if "vector" in str(error) or "embedding" in str(error)
                    else "invalid_scores"
                )
                failure = RunFailure(snapshot.crop_id, code, _FAILURE_MESSAGES[code])
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue
            except Exception:
                failure = RunFailure(
                    snapshot.crop_id,
                    "inference_error",
                    _FAILURE_MESSAGES["inference_error"],
                )
                store.mark_item_failed(_failed_item(pending_item, failure))
                failures.append(failure)
                failed += 1
                continue

            processed_at = datetime.now(UTC)
            representation = compatible_representation or CropRepresentation(
                representation_id=uuid4(),
                snapshot_id=snapshot.snapshot_id,
                model_fingerprint=model_identity.model_fingerprint,
                embedding=tuple(float(value) for value in image_vector),
                processed_at=processed_at,
                created_run_id=run_id,
            )
            reference_warnings = (
                (
                    "Reference similarity and agreement are heuristic match "
                    "criteria, not calibrated probabilities.",
                )
                if reference_set is not None
                else ()
            )
            decision = SpeciesDecision(
                decision_id=uuid4(),
                representation_id=representation.representation_id,
                config_fingerprint=config.config_fingerprint,
                assigned_species_id=result.assigned_species_id,
                best_candidate_id=result.best_candidate_id,
                confidence=result.confidence,
                tied_candidate_ids=result.tied_candidate_ids,
                candidate_scores=result.scores,
                reason=result.reason,
                warnings=result.warnings + reference_warnings,
                processed_at=processed_at,
                created_run_id=run_id,
                decision_path=(
                    reference_match.decision_path
                    if reference_match is not None
                    else "zero_shot"
                ),
                reference_set_fingerprint=(
                    reference_set.fingerprint if reference_set is not None else None
                ),
                reference_split_mode=(
                    config.reference_split_mode if reference_set is not None else None
                ),
                reference_similarity=(
                    reference_match.similarity if reference_match is not None else None
                ),
                reference_agreement=(
                    reference_match.agreement if reference_match is not None else None
                ),
                reference_neighbor_ids=(
                    reference_match.retained_reference_ids
                    if reference_match is not None
                    else ()
                ),
            )
            completed_item = RunItem(
                run_id=run_id,
                crop_id=snapshot.crop_id,
                expected_snapshot_id=snapshot.snapshot_id,
                expected_provenance_sha256=snapshot.provenance_sha256,
                resolved_input_locator=crop_path,
                status=RunItemStatus.COMPLETED,
                decision_id=decision.decision_id,
                failure_code=None,
                failure_reason=None,
                started_at=pending_item.started_at,
                completed_at=processed_at,
                lighting=snapshot.lighting,
            )
            try:
                committed = store.commit_crop_result(
                    snapshot, representation, decision, completed_item
                )
            except UnconfirmedCommitError:
                unconfirmed_crop_ids = (snapshot.crop_id,)
                failures.append(
                    RunFailure(
                        snapshot.crop_id,
                        "storage_error",
                        "crop commit status is unconfirmed",
                    )
                )
                fatal = True
                break
            if committed:
                completed += 1
                assigned += int(decision.assigned_species_id is not None)
                unknown += int(decision.assigned_species_id is None)
            else:
                skipped += 1
    except StorageError:
        return _unfinalized_run(
            run,
            completed=completed,
            skipped=skipped,
            failed=failed,
            assigned=assigned,
            unknown=unknown,
            failures=tuple(failures)
            + (RunFailure(None, "storage_error", "durable storage operation failed"),),
            unconfirmed_crop_ids=unconfirmed_crop_ids,
        )

    if unconfirmed_crop_ids:
        return _unfinalized_run(
            run,
            completed=completed,
            skipped=skipped,
            failed=failed,
            assigned=assigned,
            unknown=unknown,
            failures=tuple(failures),
            unconfirmed_crop_ids=unconfirmed_crop_ids,
        )

    status = (
        RunStatus.FAILED
        if fatal or (failed and completed + skipped == 0)
        else RunStatus.PARTIAL_FAILURE
        if failed
        else RunStatus.COMPLETE
    )
    return _finalize(
        store,
        run,
        status=status,
        completed=completed,
        skipped=skipped,
        failed=failed,
        assigned=assigned,
        unknown=unknown,
        failures=tuple(failures),
        unconfirmed_crop_ids=unconfirmed_crop_ids,
    )


def _failed_item(item: RunItem, failure: RunFailure) -> RunItem:
    return RunItem(
        run_id=item.run_id,
        crop_id=item.crop_id,
        expected_snapshot_id=item.expected_snapshot_id,
        expected_provenance_sha256=item.expected_provenance_sha256,
        resolved_input_locator=item.resolved_input_locator,
        status=RunItemStatus.FAILED,
        decision_id=None,
        failure_code=failure.code,
        failure_reason=failure.reason,
        started_at=item.started_at,
        completed_at=datetime.now(UTC),
        lighting=item.lighting,
    )


def _failure(code: str, crop_id: str, error: Exception) -> RunFailure:
    reason = _FAILURE_MESSAGES.get(code, type(error).__name__)
    if code == "crop_read_error" and isinstance(error, IsolatedCropError):
        reason = _FAILURE_MESSAGES[code]
    return RunFailure(crop_id, code, reason)


def _finalize(
    store: StoreProtocol,
    run: ProcessingRun,
    *,
    status: RunStatus,
    completed: int,
    skipped: int,
    failed: int,
    assigned: int,
    unknown: int,
    failures: tuple[RunFailure, ...],
    unconfirmed_crop_ids: tuple[str, ...] = (),
) -> ProcessingRun:
    final_run = ProcessingRun(
        run_id=run.run_id,
        started_at=run.started_at,
        completed_at=datetime.now(UTC),
        status=status,
        config_fingerprint=run.config_fingerprint,
        manifest_locator=run.manifest_locator,
        crop_root=run.crop_root,
        selection_fingerprint=run.selection_fingerprint,
        selected_count=run.selected_count,
        completed_count=completed,
        skipped_count=skipped,
        failed_count=failed,
        assigned_count=assigned,
        unknown_count=unknown,
        failures=failures,
        sanitized_settings_json=run.sanitized_settings_json,
        model_fingerprint=run.model_fingerprint,
        candidate_set_fingerprint=run.candidate_set_fingerprint,
        scoring_fingerprint=run.scoring_fingerprint,
        threshold=run.threshold,
        candidate_count=run.candidate_count,
        candidate_schema_version=run.candidate_schema_version,
        prompt_template=run.prompt_template,
        prompt_version=run.prompt_version,
        reference_set_fingerprint=run.reference_set_fingerprint,
        reference_split_mode=run.reference_split_mode,
    )
    try:
        store.finalize_run(final_run)
    except StorageError:
        return replace(
            final_run,
            durable_status_confirmed=False,
            unconfirmed_crop_ids=unconfirmed_crop_ids,
        )
    return replace(
        final_run,
        durable_status_confirmed=True,
        unconfirmed_crop_ids=unconfirmed_crop_ids,
    )


def _unfinalized_run(
    run: ProcessingRun,
    *,
    completed: int,
    skipped: int,
    failed: int,
    assigned: int,
    unknown: int,
    failures: tuple[RunFailure, ...],
    unconfirmed_crop_ids: tuple[str, ...],
) -> ProcessingRun:
    """Return local confirmed counts without claiming a durable final status."""
    return ProcessingRun(
        run_id=run.run_id,
        started_at=run.started_at,
        completed_at=None,
        status=RunStatus.FAILED,
        config_fingerprint=run.config_fingerprint,
        manifest_locator=run.manifest_locator,
        crop_root=run.crop_root,
        selection_fingerprint=run.selection_fingerprint,
        selected_count=run.selected_count,
        completed_count=completed,
        skipped_count=skipped,
        failed_count=failed,
        assigned_count=assigned,
        unknown_count=unknown,
        failures=failures,
        sanitized_settings_json=run.sanitized_settings_json,
        durable_status_confirmed=False,
        unconfirmed_crop_ids=unconfirmed_crop_ids,
        model_fingerprint=run.model_fingerprint,
        candidate_set_fingerprint=run.candidate_set_fingerprint,
        scoring_fingerprint=run.scoring_fingerprint,
        threshold=run.threshold,
        candidate_count=run.candidate_count,
        candidate_schema_version=run.candidate_schema_version,
        prompt_template=run.prompt_template,
        prompt_version=run.prompt_version,
        reference_set_fingerprint=run.reference_set_fingerprint,
        reference_split_mode=run.reference_split_mode,
    )
