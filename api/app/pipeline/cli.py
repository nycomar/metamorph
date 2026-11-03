"""Pipeline CLI.

Usage (from ``api/``)::

    .venv/bin/python -m app.pipeline.cli stages --source ../docs/test-images/ring-synthetic.png \\
        --stages ../docs/runs/stages.json --out ../docs/runs/<ts>/stages

    .venv/bin/python -m app.pipeline.cli render --images ../docs/runs/<ts>/stages \\
        --out ../docs/runs/<ts>/take.mp4 --frames 49 --width 480 --height 832
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .evolve import EvolutionSpec, render_evolution
from .stages import StageSpec, StageTuning, build_stages

log = logging.getLogger("pipeline.cli")

DEFAULT_STAGES = [
    StageSpec(label="Metal ring", prompt="a polished metal ring on dark stone, studio light, same silhouette"),
    StageSpec(label="Living plant", prompt="the same ring has become living plant matter, roots and leaves holding the same silhouette"),
    StageSpec(label="Organic flesh", prompt="the same shape turns to wet organic flesh, softly breathing, same silhouette"),
    StageSpec(label="Mechanical organism", prompt="the same form becomes a mechanical organism of brass and steel, same silhouette"),
]


def _load_stages(path: str | None) -> list[StageSpec]:
    if not path:
        return DEFAULT_STAGES
    raw = json.loads(Path(path).read_text())
    return [
        StageSpec(label=s["label"], prompt=s["prompt"], weight=float(s.get("weight", 1.0)))
        for s in raw
    ]


def _stage_images(images_dir: Path) -> list[Path]:
    """Stage images in order, preferring the manifest written by ``build_stages``."""
    manifest = images_dir / "stages.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        paths = [Path(item["path"]) for item in data]
        if 2 <= len(paths) <= 6 and all(p.exists() for p in paths):
            return paths
    return sorted(images_dir.glob("stage-*.png"))


async def cmd_stages(args: argparse.Namespace) -> None:
    stages = _load_stages(args.stages)
    out = Path(args.out)
    tuning = StageTuning(
        denoise=args.denoise,
        cn_depth=args.cn_depth,
        cn_canny=args.cn_canny,
        ipa_weight=args.ipa_weight,
        ipa_weight_type=args.ipa_weight_type,
    )
    paths = await build_stages(
        Path(args.source),
        stages,
        out,
        tuning=tuning,
        only_index=args.only_index,
        image_model=args.image_model,
    )
    print(json.dumps([str(p) for p in paths]))


async def cmd_render(args: argparse.Namespace) -> None:
    images = _stage_images(Path(args.images))
    if not 2 <= len(images) <= 6:
        sys.exit(f"render needs 2-6 stage images, found {len(images)} in {args.images}")
    spec = EvolutionSpec(
        frames=args.frames,
        width=args.width,
        height=args.height,
        seed=args.seed,
        loop=args.loop,
    )
    result = await render_evolution(images, spec, Path(args.out))
    print(json.dumps({"path": str(result.path), "duration_s": result.duration_s, "width": result.width, "height": result.height}))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stages = sub.add_parser("stages", help="generate the N stage images")
    p_stages.add_argument("--source", required=True)
    p_stages.add_argument("--stages", default=None, help="JSON list of {label, prompt, weight}")
    p_stages.add_argument("--out", required=True)
    p_stages.add_argument("--denoise", type=float, default=None, help="KSampler denoise (default: graph)")
    p_stages.add_argument("--cn-depth", type=float, default=None, help="depth ControlNet strength (default: graph)")
    p_stages.add_argument("--cn-canny", type=float, default=None, help="canny ControlNet strength (default: graph)")
    p_stages.add_argument("--ipa-weight", type=float, default=None, help="IPAdapter weight (default: graph)")
    p_stages.add_argument("--ipa-weight-type", default=None, help="IPAdapter weight_type (default: graph)")
    p_stages.add_argument("--only-index", type=int, default=None, help="generate only this stage position (0-based)")
    p_stages.add_argument(
        "--image-model",
        choices=("sdxl", "flux"),
        default=None,
        help="stage image model (default: IMAGE_MODEL env var, else sdxl)",
    )
    p_stages.set_defaults(func=cmd_stages)

    p_render = sub.add_parser("render", help="render one continuous evolution video")
    p_render.add_argument("--images", required=True)
    p_render.add_argument("--out", required=True)
    p_render.add_argument("--frames", type=int, default=49)
    p_render.add_argument("--width", type=int, default=480)
    p_render.add_argument("--height", type=int, default=832)
    p_render.add_argument("--seed", type=int, default=0)
    p_render.add_argument("--loop", action="store_true")
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
