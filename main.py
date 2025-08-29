# ================================
# FILE: main.py
# ================================
import sys, logging, os
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from pathlib import Path
from dotenv import load_dotenv

root_env = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=root_env, override=True)

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logging.getLogger(name).setLevel(logging.INFO)

app = FastAPI(title="IncidentReportHub Backend Phase 1 - Postgres")

from app.routes_inbound import router as inbound_router
from app.routes_requests import router as requests_router
from app.routes_auth import router as auth_router

app.include_router(inbound_router)
app.include_router(requests_router)
app.include_router(auth_router)

@app.get("/healthz", tags=["ops"])
def healthz():
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



@app.get("/", include_in_schema=False)
def root():
    try:
        # If docs are enabled, a soft redirect gives bots a 302 instead of 404
        return RedirectResponse(url="/docs", status_code=302)
    except Exception:
        # If docs are disabled, return a simple OK JSON instead
        return JSONResponse({"ok": True, "service": "IncidentReportHub"}, headers={"Cache-Control": "no-store"})