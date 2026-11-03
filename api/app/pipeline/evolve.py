"""Evolution render: N stage images pinned to frames -> one continuous video.

``video_model="ltx"`` (the default) uses ``workflows/evolve.json`` (LTX-2.5
distilled, single pass, video + audio). The first stage lands at frame 0 via
``LTXVImgToVideo``; stages 1..N-1 land on evenly spaced frames via chained
``LTXVAddGuide`` nodes (up to five, so 2-6 stages).

``video_model="h3"`` uses ``workflows/evolve_h3.json`` (MiniMax H3 fl2va, video +
audio). Stage 0 is ``MiniMaxH3ImageToVideo.first_frame``; stages 1..N-1 are
``MiniMaxH3AddGuide`` anchors on the same positive-conditioning chain. H3 snaps
its frame count up to the model's 17k+5 grid, so override indices are computed
from the snapped length.

In both graphs guides the current run does not need are removed from the
submitted graph, and the tail is rewired to the last used guide, so unused slots
never render a phantom stage.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ._util import FPS, download_first_output, get_client, load_workflow, override, wait_for_job

log = logging.getLogger("pipeline.evolve")

GUIDE_STRENGTH = 1.0
MIN_STAGES = 2
MAX_STAGES = 6
GUIDE_NODES = ("8", "9", "10", "11", "34", "35")       # LoadImage per stage
SCALE_NODES = ("30", "31", "32", "33", "36", "37")     # ImageScale per stage
ADD_GUIDE_NODES = ("13", "14", "15", "38", "39")       # chained guide nodes (stages 1..5)
H3_FRAME_PERIOD = 17                                     # H3 length snaps to 17k+5 frames

EVOLVE_PROMPT = (
    "An object shaped like a ring sits centered on dark stone under soft studio light, "
    "the camera locked off and perfectly static. Over the course of the clip the ring "
    "undergoes one continuous, seamless metamorphosis: it begins as a polished chrome "
    "metal ring, then slowly transforms into living plant matter with roots, stems and "
    "green leaves that hold the same ring silhouette, then the plant matter becomes wet "
    "organic flesh that softly breathes while keeping the same ring shape, and finally "
    "the flesh becomes a mechanical organism of brass and steel with articulated joints "
    "and pistons, still holding the same ring silhouette. Continuous unbroken "
    "transformation, the object never leaves its position, no cuts, no camera movement, "
    "no text, no people."
)
EVOLVE_NEGATIVE = "text, watermark, cartoon, anime, blurry, jitter, jump cut, extra objects, hands, people, low quality"


@dataclass
class EvolutionSpec:
    frames: int
    width: int
    height: int
    seed: int
    loop: bool = False


@dataclass
class RenderResult:
    path: Path
    duration_s: float
    width: int
    height: int


def _guide_indices(frames: int, count: int) -> list[int]:
    """Evenly spread ``count`` guide frames across ``frames`` (first 0, last frames-1)."""
    last = frames - 1
    return [round(i / (count - 1) * last) for i in range(count)]


def _h3_aligned_length(frames: int) -> int:
    """Snap a requested length up to MiniMax H3's 17k+5 frame grid."""
    length = max(5, frames)
    while length % H3_FRAME_PERIOD != 5:
        length += 1
    return length


async def render_evolution(
    stage_images: list[Path],
    spec: EvolutionSpec,
    out_path: Path,
    video_model: str = "ltx",
) -> RenderResult:
    """Render one continuous metamorphosis shot and write it to ``out_path``."""
    count = len(stage_images)
    if not MIN_STAGES <= count <= MAX_STAGES:
        raise ValueError(
            f"render_evolution expects {MIN_STAGES}-{MAX_STAGES} stage images, got {count}"
        )
    if spec.loop:
        log.warning("spec.loop=True is not yet wired (linear metamorphosis arc does not close a loop)")
    if video_model not in ("ltx", "h3"):
        raise ValueError(f"video_model must be 'ltx' or 'h3', got {video_model!r}")

    client = get_client()
    workflow = load_workflow("evolve_h3.json" if video_model == "h3" else "evolve.json")

    names: list[str] = []
    for path in stage_images:
        upload = await client.upload_image(str(path), path.name)
        names.append(upload.get("name") or path.name)

    wf = workflow
    for node_id, name in zip(GUIDE_NODES, names):
        wf = override(wf, node_id, "image", name)

    used_guides = ADD_GUIDE_NODES[: count - 1]
    used_scales = SCALE_NODES[:count]
    tail = used_guides[-1]

    if video_model == "h3":
        render_frames = _h3_aligned_length(spec.frames)
        idx = _guide_indices(render_frames, count)
        wf = override(wf, "12", "width", spec.width)     # MiniMaxH3ImageToVideo
        wf = override(wf, "12", "height", spec.height)
        wf = override(wf, "12", "length", render_frames)
        for node_id, frame_idx in zip(used_guides, idx[1:]):
            wf = override(wf, node_id, "frame_idx", frame_idx)
        wf = override(wf, "19", "noise_seed", spec.seed)
        for node_id in used_scales:
            wf = override(wf, node_id, "width", spec.width)
            wf = override(wf, node_id, "height", spec.height)
        wf = override(wf, "27", "filename_prefix", f"metamorph/{out_path.stem}")
        wf = override(wf, "18", "conditioning", [tail, 0])
    else:
        render_frames = spec.frames
        idx = _guide_indices(spec.frames, count)
        wf = override(wf, "12", "width", spec.width)     # LTXVImgToVideo (frame 0)
        wf = override(wf, "12", "height", spec.height)
        wf = override(wf, "12", "length", spec.frames)
        for node_id, frame_idx in zip(used_guides, idx[1:]):
            wf = override(wf, node_id, "frame_idx", frame_idx)
            wf = override(wf, node_id, "strength", GUIDE_STRENGTH)
        wf = override(wf, "16", "frames_number", spec.frames)  # audio latent must match video
        wf = override(wf, "19", "noise_seed", spec.seed)
        for node_id in used_scales:
            wf = override(wf, node_id, "width", spec.width)
            wf = override(wf, node_id, "height", spec.height)
        wf = override(wf, "27", "filename_prefix", f"metamorph/{out_path.stem}")

        # Drop guides the run does not use, and point the tail at the last real guide.
        wf = override(wf, "17", "video_latent", [tail, 2])
        wf = override(wf, "18", "positive", [tail, 0])
        wf = override(wf, "18", "negative", [tail, 1])

    unused = (
        set(ADD_GUIDE_NODES[count - 1 :])
        | set(GUIDE_NODES[count:])
        | set(SCALE_NODES[count:])
    )
    wf = {node_id: node for node_id, node in wf.items() if node_id not in unused}

    t0 = time.monotonic()
    prompt_id = await client.submit(wf)
    detail = await wait_for_job(client, prompt_id)
    await download_first_output(client, detail, out_path)

    result = RenderResult(
        path=out_path,
        duration_s=render_frames / FPS,
        width=spec.width,
        height=spec.height,
    )
    log.info("render done -> %s (%d frames, %.2fs, %.1fs wall)", out_path, render_frames, result.duration_s, time.monotonic() - t0)
    return result
