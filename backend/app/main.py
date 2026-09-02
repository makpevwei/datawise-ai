from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.agent import router as agent_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.datasets import router as datasets_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.integrations import router as integrations_router
from app.api.rate_limit import limiter
from app.api.relationships import router as relationships_router
from app.api.reports import router as reports_router
from app.api.sessions import router as sessions_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "healthy",
        "api": settings.api_v1_prefix,
        "health": f"{settings.api_v1_prefix}/health",
        "docs": "/docs",
        # Trivial, deliberately visible marker for the CI-triggered-deploy
        # end-to-end test (push to main -> CI -> automatic Cloud Run
        # deploy, no manual gcloud command run by anyone).
        "deploy_pipeline": "verified-2026-08-30",
    }


app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(health_router)  # bare /health too, for infra/LB health checks
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(datasets_router, prefix=settings.api_v1_prefix)
app.include_router(relationships_router, prefix=settings.api_v1_prefix)
app.include_router(analysis_router, prefix=settings.api_v1_prefix)
app.include_router(documents_router, prefix=settings.api_v1_prefix)
app.include_router(agent_router, prefix=settings.api_v1_prefix)
app.include_router(sessions_router, prefix=settings.api_v1_prefix)
app.include_router(reports_router, prefix=settings.api_v1_prefix)
app.include_router(integrations_router, prefix=settings.api_v1_prefix)
