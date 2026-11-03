"""ffmpeg helpers for exports and gallery thumbnails. One encode at a time."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from .storage import project_dir

log = logging.getLogger("media")

ENCODE_LOCK = asyncio.Lock()

EXPORT_NAMES = {
    "916": "export-916.mp4",
    "169": "export-169.mp4",
    "webp": "export.webp",
}


async def _ffmpeg(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {tail}")


def _video_export_args(src: Path, dest: Path, width: int, height: int) -> list[str]:
    return [
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(dest),
    ]


def _webp_export_args(src: Path, dest: Path) -> list[str]:
    return [
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-an",
        "-vf",
        "fps=24,scale=720:-2:flags=lanczos",
        "-c:v",
        "libwebp",
        "-lossless",
        "0",
        "-q:v",
        "75",
        "-compression_level",
        "4",
        "-loop",
        "0",
        str(dest),
    ]


def _thumb_args(src: Path, dest: Path) -> list[str]:
    return [
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(dest),
    ]


def _partial(path: Path) -> Path:
    return path.with_name(f"{path.stem}.partial{path.suffix}")


async def ensure_export(take_path: Path, project_id: str, fmt: str) -> Path:
    """Return the cached export, or encode it (serialised by ENCODE_LOCK)."""
    out = project_dir(project_id) / EXPORT_NAMES[fmt]
    async with ENCODE_LOCK:
        if out.exists() and out.stat().st_mtime >= take_path.stat().st_mtime:
            return out
        tmp = _partial(out)
        if fmt == "916":
            args = _video_export_args(take_path, tmp, 1080, 1920)
        elif fmt == "169":
            args = _video_export_args(take_path, tmp, 1920, 1080)
        else:
            args = _webp_export_args(take_path, tmp)
        await _ffmpeg(args)
        os.replace(tmp, out)
        log.info("export %s -> %s", fmt, out)
        return out


async def ensure_thumb(take_path: Path, project_id: str) -> Path:
    """Generate the project's first-frame JPEG once, then reuse it."""
    out = project_dir(project_id) / "thumb.jpg"
    async with ENCODE_LOCK:
        if out.exists():
            return out
        tmp = _partial(out)
        await _ffmpeg(_thumb_args(take_path, tmp))
        os.replace(tmp, out)
        log.info("thumbnail -> %s", out)
        return out
