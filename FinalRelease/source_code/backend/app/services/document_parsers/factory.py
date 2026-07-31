from sqlmodel import Session

from app.db.session import engine
from app.services.document_parsers.mineru import MinerUClient, MinerUParser, MinerUSettings
from app.services.document_parsers.mineru_official import (
    OfficialMinerUClient,
    OfficialMinerUSettings,
)
from app.services.integration_settings import get_effective_integration_config


def create_mineru_parser() -> MinerUParser:
    with Session(engine) as session:
        config, _ = get_effective_integration_config(session)
    if config.mineru_provider == "local":
        client = MinerUClient(
            MinerUSettings(
                base_url=config.mineru_local_url,
                backend=config.mineru_backend,
                language=config.mineru_language,
                parse_method=config.mineru_parse_method,
                request_timeout_seconds=config.mineru_request_timeout_seconds,
                task_timeout_seconds=config.mineru_task_timeout_seconds,
                poll_interval_seconds=config.mineru_poll_interval_seconds,
            )
        )
        return MinerUParser(client)
    if config.mineru_provider == "official":
        client = OfficialMinerUClient(
            OfficialMinerUSettings(
                base_url=config.mineru_official_api_url,
                token=config.mineru_official_api_token,
                model=config.mineru_official_api_model,
                language=config.mineru_language,
                ocr=config.mineru_ocr,
                formula_enable=config.mineru_formula_enable,
                table_enable=config.mineru_table_enable,
                request_timeout_seconds=config.mineru_request_timeout_seconds,
                request_retries=config.mineru_request_retries,
                task_timeout_seconds=config.mineru_task_timeout_seconds,
                poll_interval_seconds=config.mineru_poll_interval_seconds,
            )
        )
        return MinerUParser(client)
    raise ValueError("MinerU provider must be either 'local' or 'official'")
