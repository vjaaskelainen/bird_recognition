# Bird Recognition Constitution

## Core Principles

### I. Evidence-Grounded Answers
Answers about footage MUST be grounded in retrieved frames and their metadata. The Ask
workflow MUST cite the frames supporting each answer and MUST state when the retrieved
evidence is insufficient; it MUST NOT present unsupported claims as facts. This keeps
generation auditable and useful even when retrieval is incomplete.

### II. Privacy-Preserving Data Handling
Raw videos, extracted frames, and crops MUST remain outside version control. Ingestion MUST
exclude detected people, and published sample data MUST be checked to contain no people.
LLM credentials MUST be supplied through environment variables, never committed. These
requirements protect people captured incidentally and prevent accidental disclosure.

### III. Pretrained Models and Measured Quality
The project MUST use pretrained models and MUST NOT train or fine-tune models as part of
its core scope. Species tagging and retrieval MUST be evaluated on labeled examples, with
daylight and night results distinguished for species tagging. Evaluation claims in project
documentation MUST report measured results and known failure cases rather than imply
unverified accuracy.

### IV. Testable, Offline-Friendly Core
Core ingestion, indexing, retrieval, and answer-assembly behavior MUST be testable without
live model or LLM services wherever practical. Tests MUST mock the LLM so the standard test
suite requires neither an API key nor network access. Changes to shared data contracts or
database integration MUST include tests at the affected boundary.

### V. Small, Usable CLI-First Scope
The CLI is the primary interface. Implementation MUST prioritize a complete local workflow
from ingestion through search, grounded Q&A, and evaluation before optional UI work. The
project MUST avoid authentication, multi-user support, cloud deployment, real-time
streaming, and agent features unless the constitution is amended. Prefer the smallest
implementation that demonstrates the project goals.

## Technical and Data Constraints

The implementation uses Python 3.14 or newer, with uv for project and environment
management. The planned pipeline uses MegaDetector for animal detection, BioCLIP for
image/text embeddings and zero-shot species tagging, and PostgreSQL with pgvector for
vector storage and metadata. PostgreSQL is run locally through Compose. LLM access is via
a vision-capable API; secrets are provided only through environment variables.

Raw footage and derived private data MUST NOT be added to Git. Only a small, privacy-checked
sample set and explicitly prepared evaluation labels may be committed. Search and Ask MUST
retain frame provenance (source video, frame/time, and relevant detection metadata) so
retrieved evidence can be identified and cited.

## Development Workflow and Quality Gates

Feature work follows the repository’s Spec Kit workflow: specify, plan, tasks, implement,
and converge, reviewing each artifact before proceeding. Keep the workflow proportional to
this project’s small scope. Python conventions and agent behavior are defined by
[`AGENTS.md`](../../AGENTS.md) and the referenced project guidance; tool configuration is
defined in `pyproject.toml` and must not be duplicated here.

Before completion, run the configured Ruff lint and format checks and the pytest suite.
GitHub Actions MUST run lint and tests on pushes. Tests that would otherwise require an
LLM API MUST use a mock.

## Governance

This constitution governs project decisions. If implementation guidance conflicts with
these principles, follow the constitution or amend it before proceeding. Amendments require
an explicit rationale, review of affected specifications and implementation guidance, and
an update to the version and last-amended date. A material change to principles or scope
increments the minor version; a backward-incompatible removal or redefinition increments
the major version; clarifications that do not change requirements increment the patch
version. Compliance is reviewed during feature planning, implementation, and final quality
checks. Detailed coding conventions and agent workflow remain in `AGENTS.md` and linked
guidance rather than being duplicated here.

**Version**: 1.0.0 | **Ratified**: 2026-10-11 | **Last Amended**: 2026-10-11
