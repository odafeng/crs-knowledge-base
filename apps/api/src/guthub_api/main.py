from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from guthub_api.accounts import router as accounts_router
from guthub_api.auth import TokenVerifier
from guthub_api.comments import router as comments_router
from guthub_api.content import router as content_router
from guthub_api.content_requests import router as content_requests_router
from guthub_api.daily import router as daily_router
from guthub_api.db import open_pool
from guthub_api.errors import error_response, install_error_handling
from guthub_api.moderation import router as moderation_router
from guthub_api.push import router as push_router
from guthub_api.semantic import PerMinute, voyage
from guthub_api.semantic import router as semantic_router
from guthub_api.settings import Settings
from guthub_api.stats import router as stats_router
from guthub_api.surgeon_roster import RosterSource, fetch_roster
from guthub_api.surgeons import router as surgeons_router

API_PREFIX = "/api/v1"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAINTENANCE_RETRY_SECONDS = 600


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings: Settings = app.state.settings
    if settings.database_url is not None:
        app.state.pool = open_pool(settings.database_url.get_secret_value())
    try:
        yield
    finally:
        if app.state.pool is not None:
            app.state.pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    # contracts/openapi.yaml is the only published spec, so FastAPI's generated docs stay off.
    app = FastAPI(title="GutHub API", openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings or Settings()
    app.state.pool = None
    supabase_url = app.state.settings.supabase_url
    app.state.verifier = TokenVerifier.for_supabase(supabase_url) if supabase_url else None
    roster_url = app.state.settings.surgeon_roster_url
    app.state.roster = RosterSource(lambda: fetch_roster(roster_url)) if roster_url else None
    voyage_key = app.state.settings.voyage_api_key
    app.state.embed = voyage(voyage_key.get_secret_value()) if voyage_key else None
    app.state.search_limiter = PerMinute(app.state.settings.search_per_minute)
    if app.state.settings.writes_paused:
        # Registered first so request IDs and CORS wrap it; the check sits here, not in each route, so a new write
        # route cannot miss it. Retry-After tells the web app this is planned maintenance, not an outage.
        @app.middleware("http")
        async def pause_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            if request.method in WRITE_METHODS and request.url.path.startswith(API_PREFIX):
                return error_response(
                    request,
                    503,
                    "unavailable",
                    "Writes are paused for maintenance",
                    {"Retry-After": str(MAINTENANCE_RETRY_SECONDS)},
                )
            return await call_next(request)

    install_error_handling(app)
    if app.state.settings.cors_origins:
        # Bearer tokens, not cookies: no credentials mode, so a listed origin still cannot ride on a user's session.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app.state.settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["Retry-After"],
            max_age=600,
        )

    @app.get(f"{API_PREFIX}/health")
    def health(request: Request, response: Response) -> dict[str, str]:
        # Liveness and readiness share this endpoint: 503 while a configured database is unreachable.
        response.headers["Cache-Control"] = "no-store"
        pool = request.app.state.pool
        if pool is not None:
            try:
                with pool.connection(timeout=2) as conn:
                    conn.execute("select 1")
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ok"}

    app.include_router(content_router, prefix=API_PREFIX)
    app.include_router(daily_router, prefix=API_PREFIX)
    app.include_router(accounts_router, prefix=API_PREFIX)
    app.include_router(comments_router, prefix=API_PREFIX)
    app.include_router(moderation_router, prefix=API_PREFIX)
    app.include_router(push_router, prefix=API_PREFIX)
    app.include_router(stats_router, prefix=API_PREFIX)
    app.include_router(content_requests_router, prefix=API_PREFIX)
    app.include_router(surgeons_router, prefix=API_PREFIX)
    app.include_router(semantic_router, prefix=API_PREFIX)
    return app


app = create_app()
