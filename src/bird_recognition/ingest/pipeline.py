"""Privacy-first sampled-frame filtering and crop orchestration."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from bird_recognition.ingest.crops import (
    crop_image,
    normalized_box_to_pixels,
    publish_frame_crops,
)
from bird_recognition.ingest.detection import Detector
from bird_recognition.ingest.lighting import classify_image
from bird_recognition.ingest.manifest import (
    Manifest,
    destination_lock,
    settings_identity,
    sha256_file,
    stable_crop_id,
)
from bird_recognition.ingest.models import (
    CaptureTime,
    Detection,
    DetectionCategory,
    FrameOutcome,
    FrameResult,
    IngestSettings,
    Lighting,
    ProcessingError,
    RunSummary,
    SampledFrame,
)
from bird_recognition.ingest.video import (
    capture_start_for_video,
    derive_capture_time,
    discover_videos,
    sample_video,
)


def filter_detections(
    frame_number: int,
    detections: Sequence[Detection] | None,
    settings: IngestSettings,
    failure_reason: str | None = None,
) -> FrameResult:
    """Apply inclusive thresholds and person-first frame exclusion."""
    if detections is None or failure_reason is not None:
        return FrameResult(
            frame_number,
            FrameOutcome.FAILED,
            failure_reason=failure_reason or "detector returned no complete result",
        )
    qualified = tuple(
        replace(
            detection,
            detection_id=detection.detection_id or f"d{index:06d}",
            qualifies=(
                detection.category is DetectionCategory.ANIMAL
                and detection.confidence >= settings.animal_threshold
            )
            or (
                detection.category is DetectionCategory.PERSON
                and detection.confidence >= settings.person_threshold
            ),
        )
        for index, detection in enumerate(detections)
    )
    if any(
        detection.category is DetectionCategory.PERSON and detection.qualifies
        for detection in qualified
    ):
        outcome = FrameOutcome.PERSON_EXCLUDED
    elif any(
        detection.category is DetectionCategory.ANIMAL and detection.qualifies
        for detection in qualified
    ):
        outcome = FrameOutcome.RETAINED
    else:
        outcome = FrameOutcome.NO_ANIMAL
    return FrameResult(frame_number, outcome, detections=qualified)


def process_sampled_frame(
    frame: SampledFrame, detector: Detector, settings: IngestSettings
) -> FrameResult:
    """Detect once on a complete frame and build crops only for safe animals."""
    try:
        detections = detector.detect(frame.image)
        for detection in detections:
            normalized_box_to_pixels(detection.box, frame.width, frame.height)
        result = filter_detections(frame.frame_number, detections, settings)
        if result.outcome is not FrameOutcome.RETAINED:
            return result
        qualifying = tuple(
            detection
            for detection in result.detections
            if detection.category is DetectionCategory.ANIMAL and detection.qualifies
        )
        crops: list[object] = []
        for detection in qualifying:
            crop, _ = crop_image(frame.image, detection.box)  # type: ignore[arg-type]
            crops.append(crop)
        return replace(result, crops=tuple(crops))
    except Exception as error:
        reason = str(error) or error.__class__.__name__
        return FrameResult(
            frame.frame_number,
            FrameOutcome.FAILED,
            failure_reason=reason,
        )


def process_detection_result(
    frame_number: int,
    detections: Sequence[Detection],
    settings: IngestSettings,
) -> FrameResult:
    """Apply filtering to a controlled result, converting invalid output to failure."""
    try:
        return filter_detections(frame_number, detections, settings)
    except (ProcessingError, ValueError) as error:
        return FrameResult(frame_number, FrameOutcome.FAILED, failure_reason=str(error))


def _new_source_counts() -> dict[str, int]:
    return {
        "sampled": 0,
        "person_excluded": 0,
        "no_animal": 0,
        "retained": 0,
        "failed": 0,
        "crops": 0,
    }


def _increment_outcome(counts: dict[str, int], outcome: FrameOutcome) -> None:
    key = {
        FrameOutcome.PERSON_EXCLUDED: "person_excluded",
        FrameOutcome.NO_ANIMAL: "no_animal",
        FrameOutcome.RETAINED: "retained",
        FrameOutcome.FAILED: "failed",
    }[outcome]
    counts["sampled"] += 1
    counts[key] += 1


def _publish_result(
    manifest: Manifest,
    run_id: str,
    source_id: str,
    settings_fingerprint: str,
    frame: SampledFrame,
    result: FrameResult,
    capture_start: CaptureTime,
    settings: IngestSettings,
) -> tuple[FrameOutcome, str | None]:
    try:
        lighting = classify_image(frame.image)
    except Exception:
        lighting = Lighting.UNKNOWN
    capture_time = derive_capture_time(capture_start, frame.elapsed_seconds)
    capture_timezone = capture_start.timezone
    crop_directory = (
        manifest.output_root
        / "crops"
        / source_id
        / settings_fingerprint
        / f"frame-{frame.frame_number:08d}"
    )
    crop_records: list[dict[str, object]] = []
    published_directory: Path | None = None
    try:
        if result.outcome is FrameOutcome.RETAINED:
            detections = tuple(
                detection
                for detection in result.detections
                if detection.category is DetectionCategory.ANIMAL
                and detection.qualifies
            )
            entries = tuple(
                (detection.detection_id, crop)
                for detection, crop in zip(detections, result.crops, strict=True)
            )
            paths = publish_frame_crops(entries, crop_directory)
            published_directory = crop_directory
            for detection, path in zip(detections, paths, strict=True):
                _, box = crop_image(frame.image, detection.box)
                crop_records.append(
                    {
                        "crop_id": stable_crop_id(
                            source_id,
                            settings_fingerprint,
                            frame.frame_number,
                            detection.detection_id,
                        ),
                        "source_id": source_id,
                        "settings_fingerprint": settings_fingerprint,
                        "frame_number": frame.frame_number,
                        "detection_id": detection.detection_id,
                        "image_path": path.relative_to(manifest.output_root).as_posix(),
                        "crop_sha256": sha256_file(path),
                        "box_left": box[0],
                        "box_top": box[1],
                        "box_right": box[2],
                        "box_bottom": box[3],
                        "frame_width": frame.width,
                        "frame_height": frame.height,
                        "confidence": detection.confidence,
                        "elapsed_seconds": frame.elapsed_seconds,
                        "capture_time": capture_time,
                        "capture_timezone": capture_timezone,
                        "lighting": lighting.value,
                        "run_id": run_id,
                    }
                )
        manifest.commit_frame(
            run_id,
            source_id,
            settings_fingerprint,
            frame,
            result.outcome,
            lighting,
            result.detections,
            tuple(crop_records),
            settings,
            capture_time,
            capture_timezone,
            result.failure_reason,
        )
        return result.outcome, result.failure_reason
    except Exception as error:
        if published_directory is not None:
            shutil.rmtree(published_directory, ignore_errors=True)
        failed = FrameResult(
            frame.frame_number,
            FrameOutcome.FAILED,
            failure_reason=f"frame publication failed: {error}",
        )
        manifest.commit_frame(
            run_id,
            source_id,
            settings_fingerprint,
            frame,
            failed.outcome,
            lighting,
            (),
            (),
            settings,
            capture_time,
            capture_timezone,
            failed.failure_reason,
        )
        return FrameOutcome.FAILED, failed.failure_reason


def run_batch(
    input_root: Path,
    output_root: Path,
    settings: IngestSettings,
    detector: Detector,
) -> tuple[RunSummary, dict[str, object]]:
    """Ingest a recursive video batch and persist a reconciled run summary."""
    summary_counts = _new_source_counts()
    summary_counts.update(
        processed_sources=0,
        skipped_sources=0,
        failed_sources=0,
    )
    source_errors: list[dict[str, str]] = []
    _, settings_fingerprint = settings_identity(settings)
    with destination_lock(output_root):
        manifest = Manifest(output_root)
        manifest.recover()
        run_id, settings_fingerprint = manifest.start_run(input_root, settings)
        try:
            videos = discover_videos(input_root, settings.extensions)
        except Exception as error:
            manifest.finish_run(run_id, "failed", {"errors": [str(error)]})
            raise
        if not videos:
            manifest.finish_run(run_id, "no_input", summary_counts)
            return RunSummary(), {"run_id": run_id, "status": "no_input", "errors": []}
        for source_path in videos:
            counts = _new_source_counts()
            try:
                content_sha256 = sha256_file(source_path)
                source_id = manifest.put_source(source_path, content_sha256)
                if manifest.has_completed_source(source_id, settings_fingerprint):
                    manifest.record_skipped_source(
                        run_id, source_id, settings_fingerprint
                    )
                    summary_counts["skipped_sources"] += 1
                    continue
                manifest.begin_source(run_id, source_id, settings_fingerprint)
                source_failed = False
                source_failure_reason: str | None = None
                try:
                    capture_start = capture_start_for_video(source_path)
                    manifest.set_source_capture_time(
                        source_id,
                        capture_start.local_time,
                        capture_start.timezone,
                    )
                    for frame in sample_video(source_path, settings):
                        prior = manifest.reusable_frame(
                            run_id,
                            source_id,
                            settings_fingerprint,
                            frame.frame_number,
                        )
                        if prior is not None:
                            prior_outcome, prior_crops = prior
                            _increment_outcome(counts, prior_outcome)
                            counts["crops"] += prior_crops
                            continue
                        result = process_sampled_frame(frame, detector, settings)
                        outcome, frame_failure = _publish_result(
                            manifest,
                            run_id,
                            source_id,
                            settings_fingerprint,
                            frame,
                            result,
                            capture_start,
                            settings,
                        )
                        _increment_outcome(counts, outcome)
                        if outcome is FrameOutcome.FAILED:
                            source_failed = True
                            source_failure_reason = (
                                frame_failure or "sampled frame failed"
                            )
                            source_errors.append(
                                {
                                    "source": str(source_path),
                                    "frame": str(frame.frame_number),
                                    "error": source_failure_reason,
                                }
                            )
                        elif outcome is FrameOutcome.RETAINED:
                            counts["crops"] += len(result.crops)
                except Exception as error:
                    source_failed = True
                    source_failure_reason = str(error)
                    source_errors.append(
                        {"source": str(source_path), "error": str(error)}
                    )
                source_status = "failed" if source_failed else "processed"
                manifest.finish_source(
                    run_id,
                    source_id,
                    settings_fingerprint,
                    counts,
                    source_status,
                    source_failure_reason,
                )
                if source_failed:
                    summary_counts["failed_sources"] += 1
                else:
                    summary_counts["processed_sources"] += 1
                for key in counts:
                    summary_counts[key] += counts[key]
            except Exception as error:
                summary_counts["failed_sources"] += 1
                source_errors.append({"source": str(source_path), "error": str(error)})
        if summary_counts["failed_sources"] or summary_counts["failed"]:
            completed_count = (
                summary_counts["processed_sources"] + summary_counts["skipped_sources"]
            )
            status = "partial_failure" if completed_count else "failed"
        else:
            status = "complete"
        report = {
            **summary_counts,
            "run_id": run_id,
            "status": status,
            "errors": source_errors,
        }
        manifest.finish_run(run_id, status, report)
        manifest.close()
    summary = RunSummary(
        processed_sources=summary_counts["processed_sources"],
        skipped_sources=summary_counts["skipped_sources"],
        failed_sources=summary_counts["failed_sources"],
        sampled_frames=summary_counts["sampled"],
        person_excluded_frames=summary_counts["person_excluded"],
        no_animal_frames=summary_counts["no_animal"],
        retained_frames=summary_counts["retained"],
        failed_frames=summary_counts["failed"],
        crops=summary_counts["crops"],
    )
    return summary, report
