# Workflows

API-format ComfyUI workflow JSONs. These are shipped artifacts, not build output:
the app loads them, overrides node inputs by id, and submits them to Comfy Cloud.

- `stage.json` — one stage image (depth ControlNet + IPAdapter, img2img)
- `evolve.json` — one LTX-2.5 pass with the stage images pinned to frames as guides

## Stage defaults (updated after the sweep2 experiment)

The winning recipe is depth-only structure with a light IPAdapter style anchor.
Concrete, visible material nouns in the prompt steer SDXL; naming the source noun
or saying "the same ring becomes X" does not.

| Knob | Value |
| --- | --- |
| Source size | 768×768 |
| Depth ControlNet (`9.strength`) | 0.55 |
| Canny nodes | removed (nodes 5, 8, 10) |
| IPAdapter (`12.weight` / `12.weight_type`) | 0.25 / `linear` |
| KSampler (`14.denoise`) | 1.0 |
| KSampler steps / cfg / sampler / scheduler | 28 / 6.0 / `dpmpp_2m` / `karras` |
| Seed (`14.seed`) | 1337 |

The canny loader/preprocessor/apply nodes are gone, so `9` feeds the sampler
directly (`14.positive = ["9", 0]`, `14.negative = ["9", 1]`). Do not pass a
canny override to the CLI: there is no node 10 any more.

