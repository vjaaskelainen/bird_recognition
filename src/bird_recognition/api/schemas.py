"""Validated request and response models for API v1."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Page(BaseModel):
    """Bounded pagination parameters."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PageEnvelope(BaseModel):
    """Common response envelope for list endpoints."""

    items: list[dict[str, Any]]
    limit: int
    offset: int
    total: int


class Health(BaseModel):
    """Service and database readiness state."""

    status: str
    database: str


class ProblemDetails(BaseModel):
    """RFC 9457 response shape, also exported in OpenAPI."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[dict[str, str]] | None = None


class SearchRequest(BaseModel):
    """Search constraints equivalent to the local CLI command."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)
    species_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    lighting: str | None = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("lighting")
    @classmethod
    def lighting_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in {"day", "night"}:
            raise ValueError("lighting must be day or night")
        return value


class SearchResponse(BaseModel):
    """Search JSON payload preserving CLI fields."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    status: str
    query: str
    requested_limit: int
    returned_count: int
    warnings: list[str]
    results: list[dict[str, Any]]


class CropDetail(BaseModel):
    """CLI-compatible inspection envelope scoped to one crop."""

    schema_version: int
    run: dict[str, Any]
    items: list[dict[str, Any]]


class RunSummary(BaseModel):
    """Persisted processing-run summary."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str


class RunDetail(BaseModel):
    """Persisted processing-run detail and items."""

    schema_version: int
    run: dict[str, Any]
    items: list[dict[str, Any]]


class VisitList(BaseModel):
    """Reviewed visit aggregation report."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    run_id: str
    visit_count: int
    visits: list[dict[str, Any]]


class AskRequest(BaseModel):
    """Grounded question request requiring explicit external-transmission consent."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    question: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)
    species_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    lighting: str | None = None
    allow_external_transmission: bool = False

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value

    @field_validator("lighting")
    @classmethod
    def lighting_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in {"day", "night"}:
            raise ValueError("lighting must be day or night")
        return value


class AskResponse(BaseModel):
    """Ask JSON payload preserving CLI fields."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    status: str
    question: str
    evidence_count: int
    claims: list[dict[str, Any]]
    evidence: list[dict[str, Any]]


class IngestJobRequest(BaseModel):
    """Validated inputs for a managed ingestion command."""

    input_dir: str
    output_dir: str
    interval: float | None = Field(default=None, gt=0)
    animal_threshold: float | None = Field(default=None, ge=0, le=1)
    person_threshold: float | None = Field(default=None, ge=0, le=1)
    extensions: str | None = None


class IndexJobRequest(BaseModel):
    """Validated inputs for a managed indexing command."""

    manifest: str
    crop_root: str | None = None
    species_list: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)


class Job(BaseModel):
    """Sanitized persistent job record."""

    job_id: UUID
    kind: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    request: dict[str, Any]
    report: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class JobStartResponse(BaseModel):
    """Immediate acknowledgement for an accepted background job."""

    job_id: UUID
    status: str
