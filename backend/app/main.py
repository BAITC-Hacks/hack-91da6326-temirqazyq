from collections import defaultdict, deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.api.workspace import router as workspace_router
from app.ai.agent import AgentError, AgentManager
from app.ai.provider import Provider
from app.ai.presentation import FAILED_MESSAGE
from app.ai.settings import Settings
from app.repository import load_repository
from app.storage import Store
from app.diagnostics import log_diagnostic, log_exception


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    load_repository()
    settings = Settings.from_env()
    store = Store(settings.db_path)
    application.state.agent = AgentManager(settings, store, Provider(settings, store.path))
    try:
        yield
    finally:
        await application.state.agent.close()


app = FastAPI(
    title="Akim AI — City Command Center",
    description="Deterministic urban policy simulator. Simulation calculates; AI explains.",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Session-ID"],
)
app.include_router(router)
app.include_router(workspace_router)

_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def local_access(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in {"http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "http://127.0.0.1:8000"}:
        log_diagnostic("ORIGIN_FORBIDDEN", "Request from an unsupported origin")
        return JSONResponse(status_code=403, content={"valid": False, "errors": [{"code": "ORIGIN_FORBIDDEN", "message": "Разрешён только локальный интерфейс приложения."}]})
    if request.method == "POST" and request.url.path in {"/api/ai/runs", "/api/ai/explain", "/api/sessions"}:
        now = monotonic()
        key = (request.client.host if request.client else "local") + request.url.path
        bucket = _requests[key]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        limit = 30 if request.url.path == "/api/sessions" else 10
        if len(bucket) >= limit:
            log_diagnostic("LOCAL_RATE_LIMIT", "Local request rate limit reached")
            return JSONResponse(status_code=429, content={"valid": False, "errors": [{"code": "LOCAL_RATE_LIMIT", "message": "Слишком много запусков. Подождите минуту."}]})
        bucket.append(now)
    return await call_next(request)


@app.exception_handler(AgentError)
async def agent_error(request: Request, error: AgentError) -> JSONResponse:
    mgr = getattr(request.app.state, "agent", None)
    log_diagnostic(error.code, error.message, secret=mgr.settings.openai_api_key if mgr else "")
    return JSONResponse(status_code=409, content={"valid": False, "errors": [{"code": error.code, "message": FAILED_MESSAGE}]})


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    details = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}" for item in error.errors())
    log_diagnostic("INVALID_REQUEST", details)
    return JSONResponse(status_code=422, content={
        "valid": False,
        "errors": [{
            "code": "INVALID_REQUEST",
            "message": "Проверьте заполненные поля и повторите попытку.",
        }],
    })


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    mgr = getattr(request.app.state, "agent", None)
    log_diagnostic("HTTP_REQUEST_REJECTED", f"status={error.status_code}: {error.detail}",
                   secret=mgr.settings.openai_api_key if mgr else "")
    return JSONResponse(status_code=error.status_code, headers=error.headers, content={"detail": FAILED_MESSAGE})


@app.exception_handler(Exception)
async def internal_error(_: Request, error: Exception) -> JSONResponse:
    log_exception(error)
    return JSONResponse(status_code=500, content={
        "valid": False,
        "errors": [{"code": "INTERNAL_ERROR", "message": "Не удалось обработать запрос. Повторите попытку."}],
    })


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "akim-ai", "version": "2.0.0"}

