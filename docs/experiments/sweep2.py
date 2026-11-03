"""Diagnostic sweep 2: does material change when the source noun is removed?

Builds a depth-ControlNet-only variant of workflows/stage.json at submission time
(canny nodes removed, IPAdapter removed, denoise 1.0, 768x768, 28 steps) and
submits exactly four prompts. Saves the literal submitted graph for evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.cloud import CloudClient
from app.config import settings
from app.pipeline._util import download_first_output, load_workflow, wait_for_job

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/test-images/ring-synthetic.png"
OUT = ROOT / "docs/runs/sweep2"
SEED = 1337

P1 = (
    "a circular wreath of living green moss and vines forming a ring, wet organic "
    "texture, small leaves, dark background, studio light"
)
P2 = (
    "a ring-shaped mass of pale organic flesh, visible veins and pores, wet glossy "
    "surface, dark background, studio light"
)
P3 = (
    "a ring-shaped assembly of brass gears, copper coils and steel cables, dark "
    "background, studio lighting"
)

PLAN = [
    ("P1", P1, False),
    ("P2", P2, False),
    ("P3", P3, False),
    ("P4", P1, True),
]

DROP_WITHOUT_IPA = ("5", "8", "10", "11", "12")  # canny preprocessor, canny CN, canny apply, ipa loader, ipa apply
DROP_WITH_IPA = ("5", "8", "10")  # canny only


def make_graph(prompt: str, *, ipa: bool) -> dict[str, Any]:
    wf = copy.deepcopy(load_workflow("stage.json"))

    # Square, depth-only stage render.
    wf["17"]["inputs"]["width"] = 768
    wf["17"]["inputs"]["height"] = 768
    wf["17"]["inputs"]["crop"] = "center"
    wf["3"]["inputs"]["text"] = prompt

    # Depth ControlNet at 0.55; its output feeds the sampler directly.
    wf["9"]["inputs"]["strength"] = 0.55

    ks = wf["14"]["inputs"]
    ks.update(
        seed=SEED,
        steps=28,
        cfg=6.0,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        denoise=1.0,
        positive=["9", 0],
        negative=["9", 1],
        latent_image=["13", 0],
    )

    for node_id in DROP_WITH_IPA if ipa else DROP_WITHOUT_IPA:
        wf.pop(node_id, None)

    if ipa:
        wf["11"]["inputs"]["model"] = ["2", 0]
        wf["12"]["inputs"].update(
            model=["11", 0],
            image=["17", 0],
            weight=0.25,
            weight_type="linear",
        )
        ks["model"] = ["12", 0]
    else:
        ks["model"] = ["2", 0]

    return wf


def validate(wf: dict[str, Any]) -> None:
    """Refuse to submit a graph with a dangling node reference or stale control."""
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
    assert "ControlNetLoader" in classes
    assert "DepthAnythingV2Preprocessor" in classes
    if "IPAdapterAdvanced" in classes:
        assert wf["12"]["inputs"]["weight"] == 0.25
        assert wf["12"]["inputs"]["weight_type"] == "linear"
        assert wf["14"]["inputs"]["model"] == ["12", 0]
    else:
        assert wf["14"]["inputs"]["model"] == ["2", 0]
    assert wf["14"]["inputs"]["denoise"] == 1.0
    assert wf["14"]["inputs"]["steps"] == 28
    assert wf["9"]["inputs"]["strength"] == 0.55
    assert (wf["17"]["inputs"]["width"], wf["17"]["inputs"]["height"]) == (768, 768)
    assert wf["2"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"


def summary(wf: dict[str, Any], prompt_id: str | None = None) -> dict[str, Any]:
    return {
        "prompt_id": prompt_id,
        "prompt": wf["3"]["inputs"]["text"],
        "checkpoint": wf["2"]["inputs"]["ckpt_name"],
        "size": [wf["17"]["inputs"]["width"], wf["17"]["inputs"]["height"]],
        "steps": wf["14"]["inputs"]["steps"],
        "denoise": wf["14"]["inputs"]["denoise"],
        "seed": wf["14"]["inputs"]["seed"],
        "depth_cn_strength": wf["9"]["inputs"]["strength"],
        "canny_nodes_present": any(
            n["class_type"] == "Canny" for n in wf.values()
        ),
        "ipa_weight": wf.get("12", {}).get("inputs", {}).get("weight"),
        "ipa_weight_type": wf.get("12", {}).get("inputs", {}).get("weight_type"),
        "sampler_model_source": wf["14"]["inputs"]["model"],
        "positive_source": wf["14"]["inputs"]["positive"],
        "node_classes": sorted({n["class_type"] for n in wf.values()}),
    }


async def main(dry_run: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    graphs: list[tuple[str, str, dict[str, Any]]] = []
    for sid, prompt, ipa in PLAN:
        wf = make_graph(prompt, ipa=ipa)
        validate(wf)
        graphs.append((sid, prompt, wf))
        (OUT / f"{sid}.workflow.json").write_text(json.dumps(wf, indent=2))

    if dry_run:
        for sid, _, wf in graphs:
            print(sid, json.dumps(summary(wf), indent=2))
        print(f"dry run ok: {len(graphs)} graphs validated, nothing submitted")
        return

    if not settings.comfy_api_key:
        sys.exit("no COMFY_API_KEY / key file")

    client = CloudClient(settings.comfy_base_url, settings.comfy_api_key, timeout=90.0)
    upload = await client.upload_image(str(SOURCE), SOURCE.name)
    src_name = upload.get("name") or SOURCE.name

    manifest: list[dict[str, Any]] = []
    for sid, prompt, wf in graphs:
        wf = copy.deepcopy(wf)
        wf["1"]["inputs"]["image"] = src_name
        wf["16"]["inputs"]["filename_prefix"] = f"metamorph/sweep2_{sid}"
        validate(wf)
        (OUT / f"{sid}.workflow.json").write_text(json.dumps(wf, indent=2))

        t0 = time.monotonic()
        prompt_id = await client.submit(wf)
        print(f"{sid} submitted prompt_id={prompt_id}", flush=True)
        try:
            detail = await wait_for_job(client, prompt_id, poll_interval=4.0, timeout=900.0)
        except Exception:
            print(f"{sid} FAILED prompt_id={prompt_id}; stopping", flush=True)
            raise
        dest = OUT / f"{sid}.png"
        await download_first_output(client, detail, dest)
        seconds = round(time.monotonic() - t0, 1)
        row = summary(wf, prompt_id)
        row.update(id=sid, seconds=seconds, path=str(dest))
        manifest.append(row)
        (OUT / "sweep2.json").write_text(json.dumps(manifest, indent=2))
        print(f"{sid} -> {dest} {seconds}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
