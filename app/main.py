import logging

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import router
from app.config import get_settings


def create_app() -> FastAPI:
    get_settings()  # fail fast on missing/invalid configuration
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = FastAPI(
        title="Contract Clause Extractor",
        version="0.1.0",
        description="Extracts and structures clauses from legal contracts (PDF/DOCX).",
    )
    register_error_handlers(app)
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
