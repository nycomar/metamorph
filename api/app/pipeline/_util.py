"""Shared helpers for the pipeline: client, workflow loading, job polling, output download.

Everything GPU-side runs on Comfy Cloud through :class:`CloudClient`; this module
owns the I/O shape (submit -> poll status -> fetch outputs -> download) so that
``stages.py`` and ``evolve.py`` stay about graph overrides, not transport.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path
from typing import Any, Iterator

from ..cloud import CloudClient, CloudError
from ..config import settings

log = logging.getLogger("pipeline")

WORKFLOWS_DIR = Path(__file__).resolve().parents[3] / "workflows"

# JobStatusResponse.status enum (comfy cloud) plus synonyms seen in the wild.
SUCCESS = {"completed", "success", "done"}
TERMINAL = SUCCESS | {"error", "failed", "cancelled", "canceled"}

FPS = 24.0


def get_client() -> CloudClient:
    return CloudClient(settings.comfy_base_url, settings.comfy_api_key, settings.request_timeout_s)


def load_workflow(name: str) -> dict[str, Any]:
    path = WORKFLOWS_DIR / name
    with path.open() as fh:
        return json.load(fh)


def override(workflow: dict[str, Any], node_id: str, field: str, value: Any) -> dict[str, Any]:
    """Return a copy of ``workflow`` with one node input overridden."""
    wf = copy.deepcopy(workflow)
    wf[node_id]["inputs"][field] = value
    return wf


def iter_outputs(detail: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every output file descriptor in a job-detail ``outputs`` object.

    ComfyUI shape: ``{node_id: {images|video|videos|audio|...: [{filename, subfolder, type}]}}``.
    """
    outputs = detail.get("outputs") or {}
    if not isinstance(outputs, dict):
        return
    for entry in outputs.values():
        if not isinstance(entry, dict):
            continue
        for key in ("images", "video", "videos", "audio", "gifs", "three_d"):
            for fdesc in entry.get(key) or []:
                if isinstance(fdesc, dict) and fdesc.get("filename"):
                    yield fdesc


async def wait_for_job(
    client: CloudClient,
    prompt_id: str,
    *,
    poll_interval: float = 4.0,
    timeout: float = 1200.0,
) -> dict[str, Any]:
    """Poll ``status`` to terminal, then fetch full job detail (with outputs)."""
    t0 = asyncio.get_event_loop().time()
    while True:
        status = await client.status(prompt_id)
        st = str(status.get("status", "")).lower()
        if st in TERMINAL:
            if st not in SUCCESS:
                raise CloudError(f"job {prompt_id} ended {st!r}: {status.get('error_message') or status}")
            break
        if asyncio.get_event_loop().time() - t0 > timeout:
            raise CloudError(f"job {prompt_id} timed out after {timeout}s (last status {st!r})")
        await asyncio.sleep(poll_interval)

    detail = await client.job_detail(prompt_id)
    return detail


async def download_first_output(
    client: CloudClient,
    detail: dict[str, Any],
    dest: Path,
    *,
    kind: str | None = None,
) -> Path:
    """Download the first output file (optionally filtered by media kind) to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for fdesc in iter_outputs(detail):
        if kind and fdesc.get("type", "") != kind and not fdesc.get("filename", "").lower().endswith(kind):
            continue
        filename = fdesc["filename"]
        subfolder = fdesc.get("subfolder", "")
        ftype = fdesc.get("type", "output")
        await client.download_view(filename, subfolder, ftype, str(dest))
        return dest
    raise CloudError(f"no output file found in job detail: {json.dumps(detail.get('outputs'))[:300]}")
