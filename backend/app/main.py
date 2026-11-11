import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, incidents, infrastructure, monitoring

app = FastAPI(
    title="THRONEX API",
    description="Intelligent infrastructure monitoring platform",
    version="0.1.0",
)

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(infrastructure.router)
app.include_router(monitoring.router)
app.include_router(incidents.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}