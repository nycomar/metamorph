"""Render job handler: stage images -> one continuous evolution take."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from .pipeline.evolve import EvolutionSpec, render_evolution
from .pipeline.stages import StageSpec, build_stages
from .storage import project_dir, set_project_status, update_job

log = logging.getLogger("jobs")

# Same shape as the final proof render in docs/runs/final.
RENDER_FRAMES = 121
RENDER_WIDTH = 480
RENDER_HEIGHT = 832
RENDER_SEED = 0


def make_render_handler(conn: sqlite3.Connection):
    async def handle(row: sqlite3.Row) -> None:
        try:
            await _render(conn, row)
        except Exception:
            set_project_status(conn, row["project_id"], "error")
            raise

    return handle


async def _render(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    job_id = row["id"]
    project_id = row["project_id"]

    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if project is None:
        raise RuntimeError(f"project {project_id} no longer exists")

    stage_rows = conn.execute(
        "SELECT * FROM stages WHERE project_id=? ORDER BY position", (project_id,)
    ).fetchall()
    if not 2 <= len(stage_rows) <= 6:
        raise RuntimeError(f"render needs between 2 and 6 stages, project has {len(stage_rows)}")

    specs = [
        StageSpec(label=s["label"], prompt=s["prompt"], weight=s["weight"]) for s in stage_rows
    ]
    source = Path(project["source_path"])
    if not source.exists():
        raise RuntimeError(f"source image missing on disk: {source}")

    out_dir = project_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # A re-render rebuilds the guides from scratch; stale files must not count as progress.
    for old in out_dir.glob("stage-*.png"):
        old.unlink(missing_ok=True)
    (out_dir / "stages.json").unlink(missing_ok=True)

    set_project_status(conn, project_id, "running")
    update_job(
        conn,
        job_id,
        state="running",
        progress=0.03,
        detail=f"stage 1 of {len(specs)}",
    )

    task = asyncio.create_task(build_stages(source, specs, out_dir))
    seen = 0
    while not task.done():
        made = len(list(out_dir.glob("stage-*.png")))
        if made > seen:
            seen = made
            update_job(
                conn,
                job_id,
                state="running",
                progress=0.05 + 0.7 * (made / len(specs)),
                detail=f"stage {made} of {len(specs)}",
            )
        await asyncio.sleep(0.5)

    images = await task
    for i, image in enumerate(images):
        conn.execute(
            "UPDATE stages SET image_path=? WHERE project_id=? AND position=?",
            (str(image), project_id, i),
        )
    conn.commit()

    update_job(
        conn,
        job_id,
        state="running",
        progress=0.8,
        detail="rendering video",
    )
    set_project_status(conn, project_id, "rendering")

    take_index = conn.execute(
        "SELECT COUNT(*) FROM takes WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    out_path = out_dir / f"take-{take_index}.mp4"
    spec = EvolutionSpec(
        frames=RENDER_FRAMES,
        width=RENDER_WIDTH,
        height=RENDER_HEIGHT,
        seed=RENDER_SEED,
        loop=False,
    )
    result = await render_evolution(images, spec, out_path)

    conn.execute(
        "INSERT INTO takes (project_id, label, video_path, duration_s) VALUES (?, ?, ?, ?)",
        (project_id, f"take {take_index}", str(result.path), result.duration_s),
    )
    conn.commit()
    set_project_status(conn, project_id, "done")
    log.info("render job %s done -> %s", job_id, result.path)
