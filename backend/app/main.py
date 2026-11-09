from fastapi import FastAPI

from app.api import auth, infrastructure

app = FastAPI(
    title="THRONEX API",
    description="Intelligent infrastructure monitoring platform",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(infrastructure.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}