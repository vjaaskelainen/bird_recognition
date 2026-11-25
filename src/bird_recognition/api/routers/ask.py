"""Explicitly consented grounded question endpoint."""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID

from dotenv import dotenv_values, find_dotenv
from fastapi import APIRouter, Depends, Request

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.schemas import AskRequest, AskResponse
from bird_recognition.api.security import require_api_key
from bird_recognition.payloads import _ask_payload, ask_transmission_notice

router = APIRouter(
    tags=["ask"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question about indexed footage",
    description=(
        "Requires explicit consent to send selected crops to the configured external "
        "answer service."
    ),
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        403: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def ask(body: AskRequest, request: Request) -> dict[str, object]:
    """Retrieve evidence and answer only after explicit request-level opt-in."""
    if body.allow_external_transmission is not True:
        raise APIError(
            403,
            "opt_in_required",
            "Set allow_external_transmission to true to send selected evidence.",
        )

    from bird_recognition.ask import AskRequest as DomainAskRequest
    from bird_recognition.ask import build_search_request, execute_ask
    from bird_recognition.embed.config import resolve_ask_configuration
    from bird_recognition.embed.models import Lighting

    resources = request.app.state.resources
    try:
        dotenv_path = find_dotenv(usecwd=True)
        dotenv_environment = dotenv_values(dotenv_path) if dotenv_path else {}
        service_configuration = resolve_ask_configuration(
            process_environment=os.environ,
            dotenv_environment=dotenv_environment,
        )
        settings = resources.settings
        if not settings.database_url:
            raise APIError(
                503, "database_unavailable", "The database is not configured."
            )
        if settings.model_dir is None:
            raise APIError(
                503, "model_unavailable", "The local model is not configured."
            )
        domain_request = DomainAskRequest(
            question=body.question,
            run_id=UUID(str(body.run_id)),
            database_url=settings.database_url,
            model_dir=settings.model_dir,
            service_config=service_configuration,
            start_date=_date(body.start_date),
            end_date=_date(body.end_date),
            lighting=Lighting(body.lighting) if body.lighting else None,
            species_id=body.species_id,
            evidence_limit=body.limit,
            output_format="json",
        )
        search_request = build_search_request(domain_request)
        store = resources.get_store()
        store.preflight(read_only=True)
        context, candidates = store.load_search_collection(search_request)
        model = resources.get_model(context.model_input_view)
        executor = resources.ask_executor or execute_ask
        outcome = executor(
            domain_request,
            model,
            store,
            context=context,
            candidates=candidates,
        )
    except APIError:
        raise
    except Exception:
        raise APIError(
            500, "internal_error", "The answer service could not complete the request."
        ) from None
    payload = _ask_payload(outcome)
    payload["transmission_notice"] = ask_transmission_notice(outcome.evidence)
    return payload


def _date(value: date | None) -> date | None:
    return value
