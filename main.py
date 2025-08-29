# ================================
# FILE: main.py  (clean scaffold)
# ================================
import sys
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# 1) Logging to stdout (Render captures this)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logging.getLogger(name).setLevel(logging.INFO)

# 2) Load .env from project root (override shell for local dev)
root_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=root_env, override=True)

# 3) Create app ONCE
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

# 4) Routers
from app.routes_auth import router as auth_router
from app.routes_inbound import router as inbound_router
from app.routes_admin import router as admin_router

app.include_router(inbound_router)
app.include_router(auth_router)
app.include_router(admin_router)

# 5) Ops endpoints (your originals, preserved)
@app.get("/healthz", tags=["ops"])
def healthz():
    # local import avoids import-time surprises
    from app.database import engine
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


# # ================================
# # FILE: main.py
# # ================================
# from fastapi import FastAPI
# from dotenv import load_dotenv
# import os

# # Local modules
# from app.database import engine
# from app.routes_auth import router as auth_router
# from app.routes_inbound import router as inbound_router
# from app.routes_admin import router as admin_router
# from pathlib import Path

# root_env = Path(__file__).resolve().parent.parent / ".env"
# load_dotenv(dotenv_path=root_env, override=True) 

# show_docs = os.getenv("SHOW_DOCS", "1") == "1"
# app = FastAPI(
#     title="IncidentReportHub Backend Phase 1 - Postgres",
#     docs_url="/docs" if show_docs else None,
#     redoc_url=None,
#     openapi_url="/openapi.json" if show_docs else None,
#     swagger_ui_parameters={
#         "docExpansion": "none",
#         "defaultModelsExpandDepth": -1,
#     },
# )

# # Routers
# app.include_router(auth_router)
# app.include_router(inbound_router)
# app.include_router(admin_router)

# # Health check
# # @app.get("/healthz", tags=["ops"])
# # def healthz():
# #     try:
# #         with engine.connect() as conn:
# #             conn.exec_driver_sql("select 1")
# #         db_ok = True
# #     except Exception:
# #         db_ok = False

# from fastapi.responses import JSONResponse

# @app.get("/healthz", tags=["ops"])
# def healthz():
#     from app.database import engine  # local import avoids import-time surprises
#     status = {"ok": True, "db": False, "error": None}
#     try:
#         with engine.connect() as conn:
#             conn.exec_driver_sql("select 1")
#         status["db"] = True
#     except Exception as e:
#         status["error"] = str(e)
#     return JSONResponse(status, headers={"Cache-Control": "no-store"})


# @app.get("/ping", tags=["ops"])
# def ping():
#     return {"pong": True}
