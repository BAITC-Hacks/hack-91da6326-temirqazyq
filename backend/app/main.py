import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.repository import load_repository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    load_repository()
    yield


app = FastAPI(
    title="Akim AI — City Command Center",
    description="Deterministic urban policy simulator. Simulation calculates; AI explains.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "valid": False,
        "errors": [{
            "code": "INVALID_REQUEST",
            "message": f"{'.'.join(str(part) for part in item['loc'] if part != 'body') or 'request'}: {item['msg']}",
        } for item in error.errors()],
    })


@app.exception_handler(Exception)
async def internal_error(_: Request, error: Exception) -> JSONResponse:
    logger.error("Request failed (%s)", type(error).__name__)
    return JSONResponse(status_code=500, content={
        "valid": False,
        "errors": [{"code": "INTERNAL_ERROR", "message": "Не удалось обработать запрос. Повторите попытку."}],
    })


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "akim-ai", "version": "1.0.0"}

