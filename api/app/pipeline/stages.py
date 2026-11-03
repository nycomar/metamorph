"""Stage image generation: one source photo + N transformation prompts -> source + N PNGs.

Stage 0 is the uploaded source, copied verbatim; it never goes near a Cloud job.
Stages 1..N are the transformations the user wrote, each generated with a
silhouette-locked graph.

Two graphs are supported: ``workflows/stage.json`` (SDXL base + depth ControlNet
+ IPAdapter of the source) and ``workflows/stage_flux.json`` (FLUX.1-dev + depth
ControlNet, no IPAdapter). Both use img2img from the encoded source. Every field
we touch is listed in ``workflows/README.md``.

Select the graph with ``image_model`` (``sdxl`` or ``flux``), the ``--image-model``
CLI flag, or the ``IMAGE_MODEL`` environment variable.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ._util import download_first_output, get_client, load_workflow, override, wait_for_job

log = logging.getLogger("pipeline.stages")

# Appended to every stage prompt so the guides share a background/lighting
# and the model only has to change material, not composition.
STAGE_PROMPT_SUFFIX = ", single object centered on dark stone, soft studio lighting, photorealistic, high detail"

# One fixed seed across all stages: same init image + same anchors + same noise
# means the only thing that changes between stages is the prompt (material), so
# the guides are layout-identical — which is what makes the final morph smooth.
STAGE_SEED = 1337

# Stage 0 is the source photo, so the user supplies only what the object becomes.
MIN_TRANSFORMATION_STAGES = 1
MAX_TRANSFORMATION_STAGES = 5


@dataclass(frozen=True)
class StageModel:
    """Which graph to load and the node ids the pipeline is allowed to override."""

    workflow: str
    source: str
    positive: str
    sampler: str
    save: str
    depth: str
    ipa: str | None = None


STAGE_MODELS: dict[str, StageModel] = {
    "sdxl": StageModel(
        workflow="stage.json",
        source="1",
        positive="3",
        sampler="14",
        save="16",
        depth="9",
        ipa="12",
    ),
    "flux": StageModel(
        workflow="stage_flux.json",
        source="1",
        positive="4",
        sampler="14",
        save="16",
        depth="9",
    ),
}


def _resolve_model(image_model: str | None) -> StageModel:
    name = (image_model or settings.image_model or "sdxl").strip().lower()
    try:
        return STAGE_MODELS[name]
    except KeyError:
        valid = ", ".join(sorted(STAGE_MODELS))
        raise ValueError(f"unknown image_model {name!r}; expected one of: {valid}") from None


@dataclass
class StageSpec:
    label: str
    prompt: str
    weight: float = 1.0


@dataclass
class StageTuning:
    """Optional overrides for the stage graph's generation knobs.

    ``None`` means "leave the value from the selected stage graph".
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
    image_model: str | None = None,
) -> list[Path]:
    """Copy the source to ``stage-0.png``, then generate one PNG per transformation.

    Returns ``1 + len(stages)`` paths, in order: the source copy followed by the
    generated transformations. Each user stage describes what the object
    *becomes*, so it is rendered into ``stage-1.png`` .. ``stage-N.png``.

    ``StageSpec.weight`` is carried through to the written manifest so the
    orchestrator can later map it onto per-guide strength in the render; this
    function itself renders every stage at the same strength.

    ``tuning`` overrides the graph's denoise / ControlNet / IPAdapter knobs.
    ``only_index`` generates just one transformation stage (0-based index into
    ``stages``) while keeping its ``stage-{index + 1}.png`` filename; the source
    copy is still written.
    ``image_model`` picks ``stage.json`` (``sdxl``) or ``stage_flux.json``
    (``flux``); ``None`` uses the configured default.
    """
    if not MIN_TRANSFORMATION_STAGES <= len(stages) <= MAX_TRANSFORMATION_STAGES:
        raise ValueError(
            "build_stages expects between "
            f"{MIN_TRANSFORMATION_STAGES} and {MAX_TRANSFORMATION_STAGES} "
            f"transformation stages, got {len(stages)}"
        )

    model_name = (image_model or settings.image_model or "sdxl").strip().lower()
    model = _resolve_model(model_name)
    if model.ipa is None and tuning is not None:
        if tuning.ipa_weight is not None or tuning.ipa_weight_type is not None:
            raise ValueError(f"image_model {model_name!r} has no IPAdapter node")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Stage 0 is the photo the user uploaded: copy it, never regenerate it.
    source_copy = out_dir / "stage-0.png"
    if source.resolve() != source_copy.resolve():
        shutil.copyfile(source, source_copy)
    print(f"stage 0 (source) -> {source_copy}", flush=True)

    results: list[Path] = [source_copy]
    manifest: list[dict] = [
        {
            "label": "Source",
            "prompt": "",
            "weight": 1.0,
            "path": str(source_copy),
            "prompt_id": None,
            "seconds": 0.0,
            "image_model": None,
        }
    ]

    client = get_client()
    workflow = load_workflow(model.workflow)

    upload = await client.upload_image(str(source), source.name)
    src_name = upload.get("name") or source.name

    for i, stage in enumerate(stages, start=1):
        if only_index is not None and i - 1 != only_index:
            continue
        prompt = f"{stage.prompt}{STAGE_PROMPT_SUFFIX}"
        wf = override(workflow, model.source, "image", src_name)
        wf = override(wf, model.positive, "text", prompt)
        wf = override(wf, model.sampler, "seed", STAGE_SEED)
        wf = override(wf, model.save, "filename_prefix", f"metamorph/stage_{i}")
        if tuning is not None:
            if tuning.denoise is not None:
                wf = override(wf, model.sampler, "denoise", tuning.denoise)
            if tuning.cn_depth is not None:
                wf = override(wf, model.depth, "strength", tuning.cn_depth)
            if tuning.cn_canny is not None:
                if model.ipa is None:
                    raise ValueError(f"image_model {model_name!r} has no canny ControlNet")
                wf = override(wf, "10", "strength", tuning.cn_canny)
            if model.ipa is not None:
                if tuning.ipa_weight is not None:
                    wf = override(wf, model.ipa, "weight", tuning.ipa_weight)
                if tuning.ipa_weight_type is not None:
                    wf = override(wf, model.ipa, "weight_type", tuning.ipa_weight_type)

        t0 = time.monotonic()
        prompt_id = await client.submit(wf)
        print(
            f"transformation {i}/{len(stages)} submitted prompt_id={prompt_id}",
            flush=True,
        )
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
                "image_model": model_name,
            }
        )
        print(
            f"transformation {i}/{len(stages)} {stage.label!r} -> {out_path} "
            f"prompt_id={prompt_id} {elapsed:.1f}s",
            flush=True,
        )

    (out_dir / "stages.json").write_text(json.dumps(manifest, indent=2))
    return results
