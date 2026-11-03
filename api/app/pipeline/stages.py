"""Stage image generation: one photo + N prompts -> N silhouette-locked PNGs.

The graph is ``workflows/stage.json`` (SDXL base + ControlNet depth/edge anchors
+ IPAdapter of the source, img2img from the encoded source). Every field we touch
is listed in ``workflows/README.md``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ._util import download_first_output, get_client, load_workflow, override, wait_for_job

log = logging.getLogger("pipeline.stages")

# Appended to every stage prompt so the four guides share a background/lighting
# and the model only has to change material, not composition.
STAGE_PROMPT_SUFFIX = ", single object centered on dark stone, soft studio lighting, photorealistic, high detail"

# One fixed seed across all stages: same init image + same anchors + same noise
# means the only thing that changes between stages is the prompt (material), so
# the guides are layout-identical — which is what makes the final morph smooth.
STAGE_SEED = 1337


@dataclass
class StageSpec:
    label: str
    prompt: str
    weight: float = 1.0


@dataclass
class StageTuning:
    """Optional overrides for the stage graph's generation knobs.

    ``None`` means "leave the value from ``workflows/stage.json``".
    """

    denoise: float | None = None
    cn_depth: float | None = None
    cn_canny: float | None = None
    ipa_weight: float | None = None
    ipa_weight_type: str | None = None


async def build_stages(
    source: Path,
    stages: list[StageSpec],
    out_dir: Path,
    tuning: StageTuning | None = None,
    only_index: int | None = None,
) -> list[Path]:
    """Generate one PNG per stage, in order. Returns the paths.

    ``StageSpec.weight`` is carried through to the written manifest so the
    orchestrator can later map it onto per-guide strength in the render; this
    function itself renders every stage at the same strength.

    ``tuning`` overrides the graph's denoise / ControlNet / IPAdapter knobs.
    ``only_index`` generates just one stage position while keeping its original
    ``stage-{i}.png`` filename (items are still numbered by their position).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    client = get_client()
    workflow = load_workflow("stage.json")

    upload = await client.upload_image(str(source), source.name)
    src_name = upload.get("name") or source.name

    results: list[Path] = []
    manifest: list[dict] = []
    for i, stage in enumerate(stages):
        if only_index is not None and i != only_index:
            continue
        prompt = f"{stage.prompt}{STAGE_PROMPT_SUFFIX}"
        wf = override(workflow, "1", "image", src_name)
        wf = override(wf, "3", "text", prompt)
        wf = override(wf, "14", "seed", STAGE_SEED)
        wf = override(wf, "16", "filename_prefix", f"metamorph/stage_{i}")
        if tuning is not None:
            if tuning.denoise is not None:
                wf = override(wf, "14", "denoise", tuning.denoise)
            if tuning.cn_depth is not None:
                wf = override(wf, "9", "strength", tuning.cn_depth)
            if tuning.cn_canny is not None:
                wf = override(wf, "10", "strength", tuning.cn_canny)
            if tuning.ipa_weight is not None:
                wf = override(wf, "12", "weight", tuning.ipa_weight)
            if tuning.ipa_weight_type is not None:
                wf = override(wf, "12", "weight_type", tuning.ipa_weight_type)

        t0 = time.monotonic()
        prompt_id = await client.submit(wf)
        print(f"stage {i + 1}/{len(stages)} submitted prompt_id={prompt_id}", flush=True)
        detail = await wait_for_job(client, prompt_id)
        out_path = out_dir / f"stage-{i}.png"
        await download_first_output(client, detail, out_path)
        elapsed = time.monotonic() - t0
        results.append(out_path)
        manifest.append(
            {
                "label": stage.label,
                "prompt": stage.prompt,
                "weight": stage.weight,
                "path": str(out_path),
                "prompt_id": prompt_id,
                "seconds": round(elapsed, 1),
            }
        )
        print(
            f"stage {i + 1}/{len(stages)} {stage.label!r} -> {out_path} prompt_id={prompt_id} {elapsed:.1f}s",
            flush=True,
        )

    (out_dir / "stages.json").write_text(json.dumps(manifest, indent=2))
    return results
