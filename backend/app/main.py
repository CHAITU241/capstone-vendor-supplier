import time
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    HTTP_REQUESTS_IN_PROGRESS,
    metrics_asgi_app,
)
from app.routers import admin, ai, assistant, documents, erp, health, portal, review, suppliers
from app.services.tracing import get_langfuse_tracer

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
_UUID_SEGMENT = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_request_metrics(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    started = time.perf_counter()
    status_code = 500
    HTTP_REQUESTS_IN_PROGRESS.inc()
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_template = getattr(route, "path", None) or _UUID_SEGMENT.sub(
            "/:id", request.url.path
        )
        HTTP_REQUESTS.labels(
            method=request.method,
            route=route_template,
            status=str(status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(
            method=request.method,
            route=route_template,
        ).observe(time.perf_counter() - started)
        HTTP_REQUESTS_IN_PROGRESS.dec()


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": f"http_{exc.status_code}", "message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "The request contains invalid data.",
            "details": jsonable_encoder(exc.errors()),
        },
    )


app.include_router(health.router, prefix="/api")
app.include_router(portal.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(suppliers.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(assistant.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(erp.router, prefix="/api")
app.mount("/metrics", metrics_asgi_app())


@app.on_event("shutdown")
def flush_langfuse() -> None:
    get_langfuse_tracer().flush()


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}
