from app.website_leads import router as website_leads_router
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers.calls import router as calls_router
from app.routers.leads import router as leads_router
from app.activity_v33 import router as activity_v33_router
from app.followup_v34 import router as followup_v34_router
from app.imports_v35 import router as imports_v35_router
from app.plan_compare_v36 import router as plan_compare_v36_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="WSBCO Insurance CRM",
    version="3.6.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

app.include_router(leads_router)
app.include_router(calls_router)
app.include_router(activity_v33_router)
app.include_router(followup_v34_router)
app.include_router(imports_v35_router)
app.include_router(plan_compare_v36_router)


@app.on_event("startup")
def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "WSBCO Insurance CRM",
        "phase": "3.6",
    }

app.add_middleware(CORSMiddleware, allow_origins=["https://turning65medicaremadeeasy.com", "https://www.turning65medicaremadeeasy.com"], allow_methods=["POST"], allow_headers=["Content-Type"])

app.include_router(website_leads_router)
