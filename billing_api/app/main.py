from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import config
from .database import Base, get_engine
from .errors import ApiError
from .routers import auth, bills, payments, usage

API_V1_PREFIX = "/api/v1"


def create_app(auto_create_tables: bool | None = None) -> FastAPI:
    create_tables = config.AUTO_CREATE_TABLES if auto_create_tables is None else auto_create_tables

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if create_tables:
            from . import models  # noqa: F401  (register tables)

            Base.metadata.create_all(get_engine())
        yield

    app = FastAPI(
        title="Mobile Provider Billing API",
        version="1.0.0",
        description="SE 4458 Midterm 1 - Group 2. Versioned REST API (`/api/v1`) used by the AI "
        "billing agent and the mobile provider app. All calls go through the API Gateway.",
        lifespan=lifespan,
        docs_url=f"{API_V1_PREFIX}/docs",
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        redoc_url=None,
    )

    v1 = APIRouter(prefix=API_V1_PREFIX)
    for module in (auth, usage, bills, payments):
        v1.include_router(module.router)
    app.include_router(v1)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"] if p not in ("body", "path", "query"))
            problems.append(f"{field}: {err['msg']}" if field else err["msg"])
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "; ".join(problems)}},
        )

    return app


app = create_app()
