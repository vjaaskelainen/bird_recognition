from __future__ import annotations

from pathlib import Path

from openapi_spec_validator import validate

from bird_recognition.api.openapi import build_openapi, export_openapi


def test_openapi_is_valid_and_documents_problem_details() -> None:
    document = build_openapi()

    validate(document)

    assert document["openapi"] == "3.1.0"
    assert "/v1/search" in document["paths"]
    assert set(
        document["paths"]["/v1/crops/{crop_id}/image"]["get"]["responses"]["200"][
            "content"
        ]
    ) == {"image/jpeg", "image/png"}
    for path in document["paths"].values():
        for operation in path.values():
            if isinstance(operation, dict) and "responses" in operation:
                assert "application/problem+json" in str(operation["responses"])


def test_openapi_export_is_deterministic_and_check_detects_stale_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "openapi.json"

    assert export_openapi(output)
    assert export_openapi(output, check=True)
    output.write_text("{}\n", encoding="utf-8")
    assert not export_openapi(output, check=True)
