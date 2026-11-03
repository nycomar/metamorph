"""Project storage helpers: disk layout, validation, and row serialisation."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from .config import settings

PROJECTS_DIR = settings.data_dir / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def media_url(project_id: str, filename: str) -> str:
    return f"/media/{project_id}/{filename}"


def parse_stages(value: object) -> list[dict]:
    """Validate a stage list from multipart text or a JSON request body."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"stages is not valid JSON: {exc.msg}") from exc
    if isinstance(value, dict) and "stages" in value:
        value = value["stages"]
    if not isinstance(value, list):
        raise ValueError("stages must be a JSON array")
    if not value:
        raise ValueError("stages must contain at least one stage")

    out: list[dict] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"stages[{i}] must be an object")
        label = item.get("label")
        prompt = item.get("prompt")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"stages[{i}].label is required")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"stages[{i}].prompt is required")
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"stages[{i}].weight must be a number") from exc
        if not math.isfinite(weight):
            raise ValueError(f"stages[{i}].weight must be finite")
        out.append({"label": label.strip(), "prompt": prompt.strip(), "weight": weight})
    return out


def _stage_payload(row: sqlite3.Row) -> dict:
    project_id = row["project_id"]
    image_name = Path(row["image_path"]).name if row["image_path"] else None
    return {
        "id": row["id"],
        "position": row["position"],
        "label": row["label"],
        "prompt": row["prompt"],
        "weight": row["weight"],
        "image_url": media_url(project_id, image_name) if image_name else None,
    }


def takes_payload(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM takes WHERE project_id=? ORDER BY id", (project_id,)
    ).fetchall()
    out = []
    for row in rows:
        filename = Path(row["video_path"]).name if row["video_path"] else ""
        out.append(
            {
                "id": row["id"],
                "label": row["label"],
                "url": media_url(project_id, filename) if filename else None,
                "duration_s": row["duration_s"],
                "picked": bool(row["picked"]),
                "created_at": row["created_at"],
            }
        )
    return out


def project_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    project_id = row["id"]
    stages = conn.execute(
        "SELECT * FROM stages WHERE project_id=? ORDER BY position", (project_id,)
    ).fetchall()
    job = conn.execute(
        "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    source_name = Path(row["source_path"]).name if row["source_path"] else None
    payload = {
        "id": project_id,
        "title": row["title"],
        "created_at": row["created_at"],
        "status": row["status"],
        "stage_count": row["stage_count"],
        "source_url": media_url(project_id, source_name) if source_name else None,
        "stages": [_stage_payload(s) for s in stages],
        "takes": takes_payload(conn, project_id),
    }
    if job is not None:
        payload["job"] = {
            "id": job["id"],
            "kind": job["kind"],
            "state": job["state"],
            "progress": job["progress"],
            "detail": job["detail"],
            "error": job["error"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }
    return payload


def update_job(conn: sqlite3.Connection, job_id: str, **fields) -> None:
    if not fields:
        return
    sets = [f"{key}=?" for key in fields]
    sets.append("updated_at=datetime('now')")
    values = [*fields.values(), job_id]
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)
    conn.commit()


def set_project_status(conn: sqlite3.Connection, project_id: str, status: str) -> None:
    conn.execute("UPDATE projects SET status=? WHERE id=?", (status, project_id))
    conn.commit()
