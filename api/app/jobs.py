"""Render job handler: stage images -> one continuous evolution take."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from .config import settings
from .pipeline.evolve import EvolutionSpec, render_evolution
from .pipeline.stages import StageSpec, build_stages
from .storage import (
    MAX_TRANSFORMATION_STAGES,
    MIN_TRANSFORMATION_STAGES,
    project_dir,
    set_project_status,
    update_job,
)

log = logging.getLogger("jobs")

# Same shape as the final proof render in docs/runs/final.
RENDER_FRAMES = 121
RENDER_WIDTH = 480
RENDER_HEIGHT = 832
RENDER_SEED = 0


def _is_legacy_original(row: sqlite3.Row) -> bool:
    """True for the old model's position-0 row that described the source itself."""
    label = (row["label"] or "").strip().lower()
    prompt = (row["prompt"] or "").strip().lower()
    return label == "original" or ", unchanged" in prompt


def transformation_stage_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Drop a legacy position-0 ``Original`` row; new projects have no such row."""
    if rows and rows[0]["position"] == 0 and _is_legacy_original(rows[0]):
        return list(rows[1:])
    return list(rows)


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
    # Old drafts stored an "Original" row for the source photo; the source is now
    # always stage-0.png, so ignore that legacy row here rather than migrating.
    stage_rows = transformation_stage_rows(stage_rows)
    if not MIN_TRANSFORMATION_STAGES <= len(stage_rows) <= MAX_TRANSFORMATION_STAGES:
        raise RuntimeError(
            "render needs between "
            f"{MIN_TRANSFORMATION_STAGES} and {MAX_TRANSFORMATION_STAGES} "
            f"transformation stages, project has {len(stage_rows)}"
        )

    specs = [
        StageSpec(label=s["label"], prompt=s["prompt"], weight=s["weight"]) for s in stage_rows
    ]

    out_dir = project_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = out_dir / "source.png"
    if not source.exists() and project["source_path"]:
        source = Path(project["source_path"])
    if not source.exists():
        raise RuntimeError(f"source image missing on disk: {source}")

    # A re-render rebuilds the guides from scratch; stale files must not count as progress.
    for old in out_dir.glob("stage-*.png"):
        old.unlink(missing_ok=True)
    (out_dir / "stages.json").unlink(missing_ok=True)

    total_images = len(specs) + 1
    set_project_status(conn, project_id, "running")
    update_job(
        conn,
        job_id,
        state="running",
        progress=0.03,
        detail=f"stage 0 of {total_images} (copying source)",
    )

    task = asyncio.create_task(build_stages(source, specs, out_dir))
    seen = 0
    while not task.done():
        made = min(len(list(out_dir.glob("stage-*.png"))), total_images)
        if made > seen:
            seen = made
            update_job(
                conn,
                job_id,
                state="running",
                progress=0.05 + 0.7 * (made / total_images),
                detail=f"stage {made} of {total_images}",
            )
        await asyncio.sleep(0.5)

    images = await task
    for stage_row, image in zip(stage_rows, images[1:]):
        conn.execute(
            "UPDATE stages SET image_path=? WHERE project_id=? AND position=?",
            (str(image), project_id, stage_row["position"]),
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
    result = await render_evolution(images, spec, out_path, video_model=settings.video_model)

    conn.execute(
        "INSERT INTO takes (project_id, label, video_path, duration_s) VALUES (?, ?, ?, ?)",
        (project_id, f"take {take_index}", str(result.path), result.duration_s),
    )
    conn.commit()
    set_project_status(conn, project_id, "done")
    log.info("render job %s done -> %s", job_id, result.path)
