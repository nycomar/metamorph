# Stack decisions

## Chosen

- **FastAPI + `comfy-sdk`** — the SDK is Python-first; async submit/poll/download is exactly the app's I/O shape.
- **One in-process worker** (`asyncio`, concurrency 1) — no broker, no second service to keep alive on a 1 vCPU box. Job state lives in SQLite and is requeued on boot.
- **React + Vite + TS, Tailwind, dnd-kit** — the stage editor is drag-and-drop and judge-facing.
- **SQLite + disk** — one writer, one reader, no ops.
- **ffmpeg** — exports, crops, thumbnails. `-threads 1`; one encode at a time.
- **Caddy + systemd** — native units, same as everything else on the host.

## Rejected

- **Docker Compose** — not installed on the host, and a daemon plus image cache is real overhead on 1 vCPU / 2 GB. Native units are lighter and match the rest of the machine.
- **Celery / RQ + Redis** — a broker is a service to babysit for a queue that only ever has a handful of jobs.
- **TypeScript backend** — the official SDK is Python; hand-writing upload/poll/download in Node only to match an existing preference is extra work for no gain here.
- **MCP as the app's runtime transport** — MCP returns tool-shaped payloads for LLMs, not a stable contract. The app uses the documented HTTP endpoints; MCP stays a build-time tool in the editor.
