from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers.calls import router as calls_router
from app.routers.leads import router as leads_router
from app.activity_v33 import router as activity_v33_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="WSBCO Insurance CRM",
    version="1.2.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

app.include_router(leads_router)
app.include_router(calls_router)
app.include_router(activity_v33_router)


@app.on_event("startup")
def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "WSBCO Insurance CRM",
        "phase": "1.2",
    }
