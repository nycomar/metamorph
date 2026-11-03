from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .cloud import CloudClient, CloudError
from .config import settings
from .db import init
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")

conn = init(settings.data_dir / "app.db")
cloud = CloudClient(settings.comfy_base_url, settings.comfy_api_key, settings.request_timeout_s)
worker: Worker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    worker = Worker(conn, handlers={}, concurrency=settings.max_concurrent_jobs)
    worker.start()
    log.info("worker started (concurrency=%s)", settings.max_concurrent_jobs)
    yield


app = FastAPI(title="Object Evolution", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    out = {"ok": True, "key_loaded": bool(settings.comfy_api_key)}
    try:
        who = await cloud.whoami()
        out["cloud"] = {"status": who.get("status"), "account": who.get("id", "")[:8] + "…"}
    except CloudError as exc:
        out["cloud"] = {"error": str(exc)}
        out["ok"] = False
    return out


@app.get("/api/meta")
async def meta() -> dict:
    try:
        info = await cloud.object_info()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    ltx = sorted(k for k in info if k.startswith("LTX"))
    return {"nodes_total": len(info), "ltx_nodes": len(ltx), "has_ltx_keyframer": "LTXKeyframer" in info}


@app.get("/api/projects")
async def list_projects() -> dict:
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC LIMIT 50").fetchall()
    return {"projects": [dict(r) for r in rows]}
