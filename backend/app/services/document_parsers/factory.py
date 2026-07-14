import os

from app.services.document_parsers.mineru import MinerUClient, MinerUParser
from app.services.document_parsers.mineru_official import OfficialMinerUClient


def create_mineru_parser() -> MinerUParser:
    provider = os.getenv("TRACELAB_MINERU_PROVIDER", "local").strip().lower()
    if provider == "local":
        return MinerUParser(MinerUClient())
    if provider == "official":
        return MinerUParser(OfficialMinerUClient())
    raise ValueError(
        "TRACELAB_MINERU_PROVIDER must be either 'local' or 'official'"
    )
