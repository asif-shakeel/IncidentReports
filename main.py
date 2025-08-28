# ================================
# FILE: main.py
# ================================
from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Local modules
from app.database import engine
from app.routes_auth import router as auth_router
from app.routes_inbound import router as inbound_router
from app.routes_admin import router as admin_router

load_dotenv()

show_docs = os.getenv("SHOW_DOCS", "1") == "1"
app = FastAPI(
    title="IncidentReportHub Backend Phase 1 - Postgres",
    docs_url="/docs" if show_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if show_docs else None,
    swagger_ui_parameters={
        "docExpansion": "none",
        "defaultModelsExpandDepth": -1,
    },
)

# Routers
app.include_router(auth_router)
app.include_router(inbound_router)
app.include_router(admin_router)

# Health check
# @app.get("/healthz", tags=["ops"])
# def healthz():
#     try:
#         with engine.connect() as conn:
#             conn.exec_driver_sql("select 1")
#         db_ok = True
#     except Exception:
#         db_ok = False

from fastapi.responses import JSONResponse

@app.get("/healthz", tags=["ops"])
def healthz():
    from app.database import engine  # local import avoids import-time surprises
    status = {"ok": True, "db": False, "error": None}
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("select 1")
        status["db"] = True
    except Exception as e:
        status["error"] = str(e)
    return JSONResponse(status, headers={"Cache-Control": "no-store"})


@app.get("/ping", tags=["ops"])
def ping():
    return {"pong": True}
