"""HTTP only stores requests and reads state; run the worker separately."""
from contextlib import asynccontextmanager
import logging
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from schemas.ingestion_schema import IngestionError
from config.service_settings import get_service_settings
from core.jobs import JobStore
from api.routes import router

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


def create_app(settings=None, *, provider_settings=None):
    settings = settings or get_service_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.store = JobStore(settings.database)
        from config.settings import get_multi_agent_settings, resolve_environment
        app.state.provider_settings = provider_settings or get_multi_agent_settings(resolve_environment())
        yield

    app = FastAPI(title="PPTAI local job service", lifespan=lifespan)
    app.include_router(router, prefix="/api")
    app.mount('/studio', StaticFiles(directory=FRONTEND / 'studio', html=True), name='studio')
    app.mount('/upload', StaticFiles(directory=FRONTEND / 'upload', html=True), name='upload')

    @app.get('/', include_in_schema=False)
    def root():
        return RedirectResponse('/studio/')

    @app.exception_handler(IngestionError)
    async def ingestion_error(request: Request, error):
        return JSONResponse(status_code=error.status, content={'detail': error.public()})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error):
        logging.getLogger(__name__).exception("Service database failure", exc_info=error)
        return JSONResponse(status_code=503, content={"detail": "Job storage is unavailable. Check the local API log."})

    return app


app = create_app()
