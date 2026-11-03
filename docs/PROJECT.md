# Metamorph — project plan

Updated 2 Nov 2026, 20:52 ET. Submission closes **3 Nov, 09:00 PT / 12:00 ET**.

## What we are building

Upload one photo of an object, name its evolutionary stages, get back **one continuous take** of that object becoming each of them — metal ring → plant → flesh → machine — with no cuts. Stage images are never shown; they are pinned to frames inside a single LTX-2.5 generation, and the model invents everything between them.

## The pipeline

```
source photo
  → anchors: depth + edges (DepthAnythingV3, Canny)
  → N stage images: img2img + ControlNet(depth/edge) + IPAdapter(source)
  → guides pinned at frames 0, 1/3, 2/3, end  (LTXKeyframer / LTXVAddGuide)
  → one LTX-2.5 pass (video + audio, 24 fps, context windows for loop)
  → continuous morph video → 9:16 / 16:9 / looping WebP
```

Everything GPU-side runs on **Comfy Cloud**. Our server orchestrates, assembles and serves.

## Three parallel tracks

| Track | Owns | Never touches |
| --- | --- | --- |
| **A — Pipeline** | `api/app/pipeline/**`, `workflows/*.json`, `docs/MATRIX.md` | routes, React |
| **B — Backend** | `api/app/{main,routes,jobs,storage}.py`, `api/app/db.py` | pipeline internals, React |
| **C — Frontend** | `web/src/**` | Python |
| **D — Lead/submission** | `docs/SUBMISSION.md`, README, demo video, form | feature code |

## Contracts — read this before writing code

Three people collide only at interfaces. These are the interfaces.

### 1. Pipeline functions (A provides, B calls)

```python
# api/app/pipeline/stages.py
async def build_stages(source: Path, stages: list[StageSpec], out_dir: Path) -> list[Path]:
    '''Returns N image paths, one per stage, in order.'''

# api/app/pipeline/evolve.py
async def render_evolution(stage_images: list[Path], spec: EvolutionSpec,
                           out_path: Path) -> RenderResult:
    '''Returns RenderResult(path, duration_s, width, height).'''
```

`StageSpec(label: str, prompt: str, weight: float)`, `EvolutionSpec(frames: int, width: int, height: int, seed: int, loop: bool)`.
Both use the shared `CloudClient` (`api/app/cloud.py`) — no direct HTTP from pipeline code.

### 2. Workflow JSON contract

`workflows/stage.json` and `workflows/evolve.json` are API-format graphs. Node ids are **frozen once A1/A2 land** and documented in `workflows/README.md` as a table of `input → node id → field`. Backend overrides only fields listed there; it never rewrites graph structure.

### 3. HTTP API (B provides, C consumes)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/projects` | multipart `source` + JSON `stages` → `{id, stages[]}` |
| GET | `/api/projects/{id}` | project, stages, takes, status |
| PUT | `/api/projects/{id}/stages` | replace stage list (order matters) |
| POST | `/api/projects/{id}/render` | queue a render → `{job_id}` |
| POST | `/api/projects/{id}/stages/{pos}/reroll` | regenerate one stage, then re-render |
| GET | `/api/jobs/{job_id}/events` | SSE progress stream |
| POST | `/api/takes/{take_id}/pick` | mark the chosen take |
| GET | `/api/projects/{id}/export?format=916\|169\|webp` | download |
| GET | `/api/gallery` | finished evolutions |

### 4. SSE event shape

```
event: progress
data: {"state":"running","progress":0.42,"detail":"stage 2 of 4"}

event: done
data: {"state":"done","takes":[{"id":1,"url":"/media/take-0.mp4"}]}

event: error
data: {"state":"error","error":"..."}
```

### 5. Disk layout

```
api/data/projects/{project_id}/
  source.png
  stage-0.png … stage-N.png
  take-0.mp4 / take-1.mp4
  export-916.mp4 / export-169.mp4 / loop.webp
```

## Tickets

| # | Track | Ticket | Depends on | Done when |
| --- | --- | --- | --- | --- |
| A1 | A | Stage image generator | — | one photo + 4 prompts → 4 PNGs with silhouette preserved; CLI runs it end to end |
| A2 | A | Evolution render | A1 | 4 stage PNGs → one 5 s 9:16 MP4 with audio; guides landing on the right frames |
| A3 | A | **Quality matrix** (the gate) | A1, A2 | `docs/MATRIX.md`: 3 settings × 1 object, side-by-side, verdict morph vs dissolve, chosen settings |
| B1 | B | Projects + stages API + upload | — | POST/GET/PUT work; files under `data/projects/{id}/`; rows in SQLite |
| B2 | B | Job runner + SSE | B1, A1/A2 | render queues; SSE streams state/progress; failures surface text |
| B3 | B | Takes, export, gallery | B2 | two takes stored, pick works, 9:16 + 16:9 + WebP export, gallery lists runs |
| B4 | B | Credit guard | B2 | per-IP and daily caps return 429 with a human message |
| C1 | C | Upload + stage editor wired | B1 | upload, reorder, add/remove persist through the API |
| C2 | C | Render screen | B2 | button → job, SSE progress bar, two takes side by side, pick persists |
| C3 | C | Re-roll + export + gallery | B2, B3 | re-roll one stage re-renders; export downloads; gallery browses |
| D1 | D | Demo video + submission | A3 | 2-min video, README on a clean machine, social post, form submitted |

**Critical path:** A1 → A2 → A3. Everything else can start immediately against the contracts above; B1 and C1 use canned JSON until B2 lands.

## Definition of done (submission)

- [ ] Public repo with code, `workflows/*.json`, MIT licence, setup instructions that work on a clean machine
- [ ] ≤2 min demo video showing a real run
- [ ] Live link a stranger can use
- [ ] Social post with `#OpenSourceHiggsfield`
- [ ] Lawful, SFW, no unlicensed likenesses
- [ ] LTX-2.5 is the core model (Open Weights + LTX bonus both stay eligible)

## Working agreements

- One branch per person: `a/pipeline`, `b/backend`, `c/frontend`. PR into `main`; the box deploys `main` within 60 s of a push.
- Nobody edits another track's files without saying so in the ticket.
- `main` must build (`npm run build`, `python -c "import app.main"`) before pushing.
- Contracts change only with a note in the PR that touches them.
