# Workflows

API-format ComfyUI workflow JSONs. These are shipped artifacts, not build output:
the app loads them, overrides node inputs by id, and submits them to Comfy Cloud.

Planned:

- `stage.json` — anchors + one stage image (ControlNet depth/edge + IPAdapter)
- `evolve.json` — one LTX-2.5 pass with the stage images pinned to frames as guides

Until the quality matrix is run, node ids and input names are placeholders.
