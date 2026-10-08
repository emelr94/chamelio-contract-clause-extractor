from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_session
from app.services.extractor import ClauseExtractor, Extractor
from app.services.llm import ClauseLLM


@lru_cache
def get_extractor() -> Extractor:
    settings = get_settings()
    return ClauseExtractor(
        ClauseLLM(settings),
        chunk_chars=settings.chunk_chars,
        concurrency=settings.llm_concurrency,
        chunk_timeout_s=settings.chunk_timeout_s,
    )


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ExtractorDep = Annotated[Extractor, Depends(get_extractor)]
