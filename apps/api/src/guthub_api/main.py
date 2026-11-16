from fastapi import FastAPI, Response

from guthub_api.errors import install_error_handling
from guthub_api.settings import Settings

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    # contracts/openapi.yaml is the only published spec, so FastAPI's generated docs stay off.
    app = FastAPI(title="GutHub API", openapi_url=None, docs_url=None, redoc_url=None)
    app.state.settings = settings or Settings()
    install_error_handling(app)

    @app.get(f"{API_PREFIX}/health")
    def health(response: Response) -> dict[str, str]:
        # Liveness and readiness share this endpoint; it will return 503 once a required dependency is down.
        response.headers["Cache-Control"] = "no-store"
        return {"status": "ok"}

    return app


app = create_app()
