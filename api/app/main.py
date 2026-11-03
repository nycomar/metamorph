from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .cloud import CloudClient, CloudError
from .config import settings
from .credits import check_and_record, client_ip
from .db import init
from .jobs import make_rerender_handler, make_render_handler, transformation_stage_rows
from .media import ensure_export, ensure_thumb
from .pipeline.stages import StageSpec, build_stages
from .storage import (
    MAX_TRANSFORMATION_STAGES,
    MIN_TRANSFORMATION_STAGES,
    PROJECTS_DIR,
    media_url,
    parse_stages,
    project_dir,
    project_payload,
    take_payload,
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
        handlers={
            "render": make_render_handler(conn),
            "rerender": make_rerender_handler(conn),
        },
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


_VIDEO_MODEL_LABELS = {"h3": "MiniMax H3", "ltx": "LTX-2.5"}
_IMAGE_MODEL_LABELS = {"sdxl": "SDXL", "flux": "FLUX.1 dev"}


@app.get("/api/meta")
async def meta() -> dict:
    try:
        info = await cloud.object_info()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    ltx_nodes = sum(1 for k in info if k.startswith("LTX"))
    h3_nodes = sum(1 for k in info if "MiniMaxH3" in k)
    video_model = settings.video_model
    image_model = settings.image_model
    return {
        "nodes_total": len(info),
        "video_model": video_model,
        "video_model_label": _VIDEO_MODEL_LABELS.get(video_model, video_model),
        "image_model": image_model,
        "image_model_label": _IMAGE_MODEL_LABELS.get(image_model, image_model),
        "ltx_nodes": ltx_nodes,
        "h3_nodes": h3_nodes,
    }


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
async def queue_render(project_id: str, request: Request) -> dict:
    row = _project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    stage_rows = conn.execute(
        "SELECT * FROM stages WHERE project_id=? ORDER BY position", (project_id,)
    ).fetchall()
    count = len(transformation_stage_rows(stage_rows))
    if not MIN_TRANSFORMATION_STAGES <= count <= MAX_TRANSFORMATION_STAGES:
        raise HTTPException(
            status_code=400,
            detail=(
                "render needs between "
                f"{MIN_TRANSFORMATION_STAGES} and {MAX_TRANSFORMATION_STAGES} "
                f"transformation stages, project has {count}"
            ),
        )

    decision = check_and_record(conn, client_ip(request))
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            content={"error": decision.error, "retry_after_s": decision.retry_after_s},
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


@app.post("/api/takes/{take_id}/pick")
async def pick_take(take_id: int) -> dict:
    take = conn.execute("SELECT * FROM takes WHERE id=?", (take_id,)).fetchone()
    if take is None:
        raise HTTPException(status_code=404, detail=f"take {take_id} not found")
    with conn:
        conn.execute("UPDATE takes SET picked=0 WHERE project_id=?", (take["project_id"],))
        conn.execute("UPDATE takes SET picked=1 WHERE id=?", (take_id,))
    take = conn.execute("SELECT * FROM takes WHERE id=?", (take_id,)).fetchone()
    return take_payload(take)


@app.get("/api/projects/{project_id}/export")
async def export_project(project_id: str, format: str = "916"):
    if format not in ("916", "169", "webp"):
        raise HTTPException(status_code=400, detail="format must be one of: 916, 169, webp")
    if _project_row(project_id) is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    take = conn.execute(
        "SELECT * FROM takes WHERE project_id=? ORDER BY picked DESC, id ASC LIMIT 1",
        (project_id,),
    ).fetchone()
    if take is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} has no takes")
    take_path = Path(take["video_path"]) if take["video_path"] else None
    if take_path is None or not take_path.exists():
        raise HTTPException(status_code=404, detail="picked take is missing on disk")

    try:
        out = await ensure_export(take_path, project_id, format)
    except RuntimeError as exc:
        log.exception("export failed for %s (%s)", project_id, format)
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc

    media_type = "image/webp" if format == "webp" else "video/mp4"
    return FileResponse(out, media_type=media_type, filename=out.name)


@app.get("/api/gallery")
async def gallery() -> dict:
    rows = conn.execute(
        """
        SELECT p.id, p.created_at, t.video_path, t.duration_s
        FROM projects p
        JOIN takes t ON t.id = (
            SELECT id FROM takes WHERE project_id=p.id ORDER BY picked DESC, id ASC LIMIT 1
        )
        ORDER BY p.created_at DESC, p.rowid DESC
        """
    ).fetchall()

    projects = []
    for row in rows:
        take_path = Path(row["video_path"]) if row["video_path"] else None
        take_url = None
        thumbnail_url = None
        if take_path is not None and take_path.exists():
            take_url = media_url(row["id"], take_path.name)
            try:
                thumb = await ensure_thumb(take_path, row["id"])
                thumbnail_url = media_url(row["id"], thumb.name)
            except RuntimeError:
                log.exception("thumbnail failed for %s", row["id"])
        projects.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "thumbnail_url": thumbnail_url,
                "take_url": take_url,
                "duration_s": row["duration_s"],
            }
        )
    return {"projects": projects}


@app.post("/api/projects/{project_id}/stages/{position}/reroll")
async def reroll_stage(project_id: str, position: int, request: Request):
    row = _project_row(project_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")

    stage_rows = transformation_stage_rows(
        conn.execute(
            "SELECT * FROM stages WHERE project_id=? ORDER BY position", (project_id,)
        ).fetchall()
    )
    if not 1 <= position <= len(stage_rows):
        raise HTTPException(
            status_code=400,
            detail=(
                f"position must be between 1 and {len(stage_rows)}; "
                "stage 0 is the source copy and cannot be re-rolled"
            ),
        )

    out_dir = project_dir(project_id)
    source = out_dir / "source.png"
    if not source.exists() and row["source_path"]:
        source = Path(row["source_path"])
    if not source.exists():
        raise HTTPException(status_code=500, detail=f"source image missing on disk: {source}")

    decision = check_and_record(conn, client_ip(request))
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            content={"error": decision.error, "retry_after_s": decision.retry_after_s},
        )

    stage_row = stage_rows[position - 1]
    specs = [
        StageSpec(label=s["label"], prompt=s["prompt"], weight=s["weight"])
        for s in stage_rows
    ]
    manifest_path = out_dir / "stages.json"
    old_manifest = None
    if manifest_path.exists():
        try:
            old_manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            old_manifest = None

    new_seed = secrets.randbelow(2**31)
    try:
        await build_stages(
            source,
            specs,
            out_dir,
            only_index=position - 1,
            seed=new_seed,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("re-roll failed for %s stage %s", project_id, position)
        raise HTTPException(status_code=502, detail=f"stage re-roll failed: {str(exc)[:300]}") from exc

    image_path = out_dir / f"stage-{position}.png"
    if not image_path.exists():
        raise HTTPException(status_code=500, detail="re-rolled stage image was not written")
    conn.execute(
        "UPDATE stages SET image_path=? WHERE id=?",
        (str(image_path), stage_row["id"]),
    )
    conn.commit()

    new_items: list[dict] = []
    try:
        new_items = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        new_items = []
    replacement = next(
        (item for item in new_items if Path(item.get("path", "")).name == image_path.name),
        None,
    )
    if isinstance(old_manifest, list) and replacement is not None:
        merged = list(old_manifest)
        replaced = False
        for i, item in enumerate(merged):
            if Path(item.get("path", "")).name == image_path.name:
                merged[i] = replacement
                replaced = True
                break
        if not replaced:
            merged.append(replacement)
        manifest_path.write_text(json.dumps(merged, indent=2))

    prompt_id = (replacement or {}).get("prompt_id")
    job_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            "INSERT INTO jobs (id, project_id, kind, state, progress, detail, prompt_id) "
            "VALUES (?, ?, 'rerender', 'queued', 0, 'queued', ?)",
            (job_id, project_id, prompt_id),
        )
        conn.execute("UPDATE projects SET status='queued' WHERE id=?", (project_id,))
    log.info(
        "re-roll %s stage %s seed=%s prompt_id=%s -> job %s",
        project_id,
        position,
        new_seed,
        prompt_id,
        job_id,
    )
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
