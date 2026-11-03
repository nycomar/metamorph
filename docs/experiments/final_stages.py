"""Render the four final stages with the sweep2 winning recipe.

Prompts are used verbatim (no pipeline suffix). The graph is workflows/stage.json
after the recipe update: depth ControlNet only at 0.55, IPAdapter 0.25 linear,
denoise 1.0, 768x768, seed 1337, 28 steps, cfg 6, dpmpp_2m/karras.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.cloud import CloudClient
from app.config import settings
from app.pipeline._util import download_first_output, load_workflow, override, wait_for_job

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/test-images/ring-synthetic.png"
OUT = ROOT / "docs/runs/final/stages"
SEED = 1337

PROMPTS = [
    (
        "metal",
        "a polished silver metal ring, brushed steel surface, dark stone floor, studio light, dark background",
    ),
    (
        "plant",
        "a circular wreath of living green moss and vines forming a ring, wet organic texture, small leaves, dark background, studio light",
    ),
    (
        "flesh",
        "a ring-shaped mass of wet pink muscle tissue, visible veins and pores, glistening raw organic surface, dark background, studio light",
    ),
    (
        "machine",
        "a ring-shaped machine of brass gears, copper coils and steel cables, exposed mechanical parts, bolts and pistons, dark background, studio light",
    ),
]


def make_graph(prompt: str, index: int) -> dict[str, Any]:
    wf = load_workflow("stage.json")
    wf = override(wf, "3", "text", prompt)
    wf = override(wf, "14", "seed", SEED)
    wf = override(wf, "16", "filename_prefix", f"metamorph/final_{index}")
    return wf


def validate(wf: dict[str, Any]) -> None:
    ids = set(wf)
    for node_id, node in wf.items():
        for field, value in node.get("inputs", {}).items():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] not in ids
            ):
                raise ValueError(f"node {node_id}.{field} -> missing node {value[0]}")

    classes = {n["class_type"] for n in wf.values()}
    assert "Canny" not in classes, classes
    assert "DepthAnythingV2Preprocessor" in classes
    assert "IPAdapterAdvanced" in classes
    assert wf["12"]["inputs"]["weight"] == 0.25
    assert wf["12"]["inputs"]["weight_type"] == "linear"
    assert wf["14"]["inputs"]["model"] == ["12", 0]
    assert wf["14"]["inputs"]["denoise"] == 1.0
    assert wf["14"]["inputs"]["steps"] == 28
    assert wf["14"]["inputs"]["cfg"] == 6.0
    assert wf["14"]["inputs"]["sampler_name"] == "dpmpp_2m"
    assert wf["14"]["inputs"]["scheduler"] == "karras"
    assert wf["14"]["inputs"]["seed"] == SEED
    assert wf["9"]["inputs"]["strength"] == 0.55
    assert wf["14"]["inputs"]["positive"] == ["9", 0]
    assert wf["14"]["inputs"]["negative"] == ["9", 1]
    assert (wf["17"]["inputs"]["width"], wf["17"]["inputs"]["height"]) == (768, 768)
    assert wf["2"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"


async def main(dry_run: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    graphs = [(i, label, prompt, make_graph(prompt, i)) for i, (label, prompt) in enumerate(PROMPTS)]
    for _, _, _, wf in graphs:
        validate(wf)

    if dry_run:
        print(f"dry run ok: {len(graphs)} graphs validated, nothing submitted")
        return

    if not settings.comfy_api_key:
        sys.exit("no COMFY_API_KEY / key file")

    client = CloudClient(settings.comfy_base_url, settings.comfy_api_key, timeout=90.0)
    upload = await client.upload_image(str(SOURCE), SOURCE.name)
    src_name = upload.get("name") or SOURCE.name

    manifest: list[dict[str, Any]] = []
    for i, label, prompt, wf in graphs:
        wf = override(wf, "1", "image", src_name)
        validate(wf)
        (OUT / f"stage-{i}.workflow.json").write_text(json.dumps(wf, indent=2))

        t0 = time.monotonic()
        prompt_id = await client.submit(wf)
        print(f"stage {i} ({label}) submitted prompt_id={prompt_id}", flush=True)
        try:
            detail = await wait_for_job(client, prompt_id, poll_interval=4.0, timeout=900.0)
        except Exception:
            print(f"stage {i} ({label}) FAILED prompt_id={prompt_id}; stopping", flush=True)
            raise
        dest = OUT / f"stage-{i}.png"
        await download_first_output(client, detail, dest)
        seconds = round(time.monotonic() - t0, 1)
        manifest.append(
            {
                "label": label,
                "prompt": prompt,
                "prompt_id": prompt_id,
                "seconds": seconds,
                "path": str(dest),
                "seed": SEED,
            }
        )
        (OUT / "stages.json").write_text(json.dumps(manifest, indent=2))
        print(f"stage {i} ({label}) -> {dest} prompt_id={prompt_id} {seconds}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
