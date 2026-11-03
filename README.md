# Metamorph — Object Evolution

Turn **one photograph of an object** into a single, unbroken shot of that object transforming into the things you describe — a metal ring into moss, flesh and machinery; a skeleton into marble and brass — with synchronized sound, in one continuous take.

Built for the [Comfy Open Source Higgsfield challenge](https://comfy.org/open-source-higgsfield/). ComfyUI + Comfy Cloud, MiniMax H3 (default) or LTX-2.5 (open weights) for video, SDXL for the stage images.

[![watch the clip](docs/runs/final/frame-01.png)](docs/runs/final/take-121f.mp4)

## How it works

The transformation is **one generation**, not a slideshow. Your photo is the first frame; the stages you describe become images that are pinned to specific frames *inside* the video model's timeline, and everything between them is generated.

```
your photo ──► structural anchors (depth map, edges)
                     │
                     ▼
        one image per stage you describe        (SDXL + depth ControlNet + IPAdapter,
        "encrusted with fossil stone"            so the silhouette survives)
                     │
                     ▼
        stages pinned at frames 0 … N           (MiniMax H3 guides, or LTX-2.5 guides)
                     │
                     ▼
        one continuous clip + audio ──► 9:16 / 16:9 / looping WebP
```

**A note on prompting that cost us hours:** image models do not edit objects, they draw them. Describing the *destination* — `a circular wreath of living green moss and vines` — works; narrating a transformation — `the same ring has become plant` — produces a ring, every time, no matter how the sampler is tuned.

## Requirements

- Python 3.11+ (3.13 tested), Node 20+ (24 tested), ffmpeg 6+
- A Comfy Cloud account with API access and credits — <https://platform.comfy.org> → API Keys

## Quickstart

```bash
git clone https://github.com/nycomar/metamorph.git
cd metamorph

# 1. API
cd api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export COMFY_API_KEY=comfyui-...          # or COMFY_API_KEY_FILE=/path/to/key
uvicorn app.main:app --port 8010

# 2. Web
cd ../web
npm install
npm run dev        # http://localhost:5173, proxies /api to :8010
```

Open the app, drop a photo, write what it should become (1–5 stages), press **Evolve**.

For a production-style run: `npm run build` and serve `web/dist` with any static server, proxying `/api` and `/media` to the API.

## Using it

1. **Drop a photo.** It becomes the first frame — there is nothing to describe.
2. **Write destinations**, one card each: a label and a prompt describing the material or state (`Fossil` / `encrusted with pale fossil stone, cracks and sediment`).
3. **Evolve.** Two takes come back; pick one.
4. **Re-roll a single stage** if one didn't land, then **export** 9:16, 16:9 or a looping WebP.

## How the pieces fit

| Part | What it does |
| --- | --- |
| `api/app/pipeline/stages.py` | copies your photo as `stage-0.png`, generates one image per stage |
| `api/app/pipeline/evolve.py` | pins those images into one video generation (`h3` default, `ltx` optional) |
| `api/app/jobs.py` | background render job → stages → video → take |
| `api/app/credits.py` | per-IP and global render limits, enforced before anything is spent |
| `api/app/media.py` | exports (9:16, 16:9, WebP), thumbnails |
| `workflows/` | the ComfyUI graphs as data — API format for submission, `workflows/ui/` to open on the canvas |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/projects` | multipart `source` + `stages` JSON → project |
| `GET` | `/api/projects/{id}` | project, stages, takes, job state |
| `PUT` | `/api/projects/{id}/stages` | replace the ordered destination list (1–5) |
| `POST` | `/api/projects/{id}/render` | queue a render → `{job_id}` |
| `POST` | `/api/projects/{id}/stages/{pos}/reroll` | regenerate one stage, re-render |
| `GET` | `/api/jobs/{id}/events` | SSE progress (`state`, `progress`, `detail`) |
| `POST` | `/api/takes/{id}/pick` | mark the chosen take |
| `GET` | `/api/projects/{id}/export?format=916\|169\|webp` | download an export |
| `GET` | `/api/gallery` | finished runs with thumbnails |

Full contract, disk layout and SSE shape: [`docs/PROJECT.md`](docs/PROJECT.md).

## Workflows

- `workflows/stage.json` — SDXL base 1.0, depth ControlNet 0.55, IPAdapter 0.25 linear, denoise 1.0, 28 steps
- `workflows/evolve_h3.json` — MiniMax H3, stages pinned with `MiniMaxH3AddGuide`
- `workflows/evolve.json` — LTX-2.5 22B distilled, stages pinned with `LTXVAddGuide`
- `workflows/ui/*.ui.json` — the same graphs in UI format; drag onto the ComfyUI canvas to inspect or edit
- `workflows/README.md` — the `input → node id → field` table for every graph

## Cost and limits

One evolution is one stage job per destination plus one video pass. The server refuses more than **3 renders per IP per hour** and **40 per day** by default (`RENDER_PER_IP_HOUR`, `RENDER_GLOBAL_DAY`), before any Cloud work starts.

## Licence

MIT — see [LICENSE](LICENSE).
