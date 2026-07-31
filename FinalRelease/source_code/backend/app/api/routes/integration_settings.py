from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.integration_settings import (
    IntegrationProbeRequest,
    IntegrationProbeResult,
    IntegrationSettingsRead,
    IntegrationSettingsUpdate,
)
from app.services.document_parsers.jobs import reset_paper_parsing_service
from app.services.integration_probe import run_integration_probe
from app.services.integration_settings import (
    get_effective_integration_config,
    integration_config_to_read,
    save_integration_config,
)

router = APIRouter(prefix="/settings/integrations", tags=["settings"])


@router.get("", response_model=IntegrationSettingsRead)
def read_integration_settings(
    session: Session = Depends(get_session),
) -> IntegrationSettingsRead:
    config, source = get_effective_integration_config(session)
    return integration_config_to_read(config, source)


@router.put("", response_model=IntegrationSettingsRead)
def update_integration_settings(
    payload: IntegrationSettingsUpdate,
    session: Session = Depends(get_session),
) -> IntegrationSettingsRead:
    config = save_integration_config(session, payload)
    reset_paper_parsing_service()
    return integration_config_to_read(config, "application")


@router.post("/probe", response_model=IntegrationProbeResult)
def probe_integration_endpoint(
    payload: IntegrationProbeRequest,
    session: Session = Depends(get_session),
) -> IntegrationProbeResult:
    """Check whether the given (or stored) credentials actually reach the provider.

    Always answers 200 with ``ok=false`` on failure so the dialog can show the provider's own
    message; a transport error is a legitimate probe result, not an API error.
    """

    return run_integration_probe(session, payload)
