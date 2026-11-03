from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .cloud import CloudClient, CloudError
from .config import settings
from .db import init
from .jobs import make_render_handler
from .storage import (
    PROJECTS_DIR,
    parse_stages,
    project_dir,
    project_payload,
    takes_payload,
)
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")

conn = init(settings.data_dir / "app.db")
cloud = CloudClient(settings.comfy_base_url, settings.comfy_api_key, settings.request_timeout_s)
worker: Worker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker
    worker = Worker(
        conn,
        handlers={"render": make_render_handler(conn)},
        concurrency=settings.max_concurrent_jobs,
    )
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
app.mount("/media", StaticFiles(directory=str(PROJECTS_DIR)), name="media")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _project_row(project_id: str):
    return conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()


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


@app.post("/api/projects", status_code=201)
async def create_project(
    source: UploadFile = File(...),
    stages: str = Form(...),
    title: str | None = Form(None),
) -> dict:
    try:
        specs = parse_stages(stages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = await source.read()
    if not data:
        raise HTTPException(status_code=400, detail="source image is empty")

    project_id = uuid.uuid4().hex
    dest = project_dir(project_id) / "source.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    clean_title = title.strip() if isinstance(title, str) and title.strip() else None
    with conn:
        conn.execute(
            "INSERT INTO projects (id, title, source_path, stage_count, status) "
            "VALUES (?, ?, ?, ?, 'draft')",
            (project_id, clean_title, str(dest.resolve()), len(specs)),
        )
        for position, spec in enumerate(specs):
            conn.execute(
                "INSERT INTO stages (project_id, position, label, prompt, weight) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, position, spec["label"], spec["prompt"], spec["weight"]),
            )

    return project_payload(conn, _project_row(project_id))


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    row = _project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return project_payload(conn, row)


@app.put("/api/projects/{project_id}/stages")
async def replace_stages(project_id: str, request: Request) -> dict:
    row = _project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body must be valid JSON") from exc
    try:
        specs = parse_stages(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with conn:
        conn.execute("DELETE FROM stages WHERE project_id=?", (project_id,))
        for position, spec in enumerate(specs):
            conn.execute(
                "INSERT INTO stages (project_id, position, label, prompt, weight) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, position, spec["label"], spec["prompt"], spec["weight"]),
            )
        conn.execute(
            "UPDATE projects SET stage_count=?, status='draft' WHERE id=?",
            (len(specs), project_id),
        )

    return project_payload(conn, _project_row(project_id))


@app.post("/api/projects/{project_id}/render")
async def queue_render(project_id: str) -> dict:
    row = _project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    count = conn.execute(
        "SELECT COUNT(*) FROM stages WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    if count != 4:
        raise HTTPException(
            status_code=400,
            detail=f"render needs exactly 4 stages, project has {count}",
        )

    job_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO jobs (id, project_id, kind, state, progress, detail) "
            "VALUES (?, ?, 'render', 'queued', 0, 'queued')",
            (job_id, project_id),
        )
        conn.execute("UPDATE projects SET status='queued' WHERE id=?", (project_id,))
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    if conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")

    async def stream():
        last: tuple | None = None
        last_beat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                yield _sse("error", {"state": "error", "error": f"job {job_id} not found"})
                return

            state = row["state"]
            if state == "done":
                yield _sse(
                    "done",
                    {"state": "done", "takes": takes_payload(conn, row["project_id"])},
                )
                return
            if state == "error":
                yield _sse("error", {"state": "error", "error": row["error"] or "render failed"})
                return

            detail = row["detail"] or ""
            progress = float(row["progress"] or 0)
            snap = (state, round(progress, 3), detail)
            now = time.monotonic()
            if snap != last:
                yield _sse(
                    "progress",
                    {"state": state, "progress": progress, "detail": detail},
                )
                last = snap
                last_beat = now
            elif now - last_beat >= 15:
                yield ": ping\n\n"
                last_beat = now
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
