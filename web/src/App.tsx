import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  api,
  type ApiStage,
  type Health,
  type Job,
  type Meta,
  type StageInput,
  type Take,
} from "./api";

type Stage = { id: string; label: string; prompt: string; weight: number };

type RenderState = {
  jobId: string;
  state: string;
  progress: number;
  detail: string;
  error: string | null;
};

type SaveState = "idle" | "saving" | "saved" | "error";

const MIN_STAGES = 2;
const MAX_STAGES = 6;

function objectPhrase(description: string): string {
  return description.trim().replace(/^(?:an?|the)\s+/i, "");
}

function buildStarterStages(description: string): Stage[] {
  const object = objectPhrase(description);
  return [
    { id: `s${crypto.randomUUID()}`, label: "Original", prompt: `a ${object}, unchanged, studio light`, weight: 1.0 },
    { id: `s${crypto.randomUUID()}`, label: "Moss", prompt: `a ${object} overgrown with living moss and vines, wet organic texture`, weight: 1.0 },
    { id: `s${crypto.randomUUID()}`, label: "Flesh", prompt: `a ${object} turned to pale wet muscle tissue, veins and pores`, weight: 1.0 },
    { id: `s${crypto.randomUUID()}`, label: "Machine", prompt: `a ${object} rebuilt from brass gears, copper coils and steel cables`, weight: 1.0 },
  ];
}

const ACTIVE_RENDER_STATES = new Set(["queued", "running"]);

function isStagesValid(list: Stage[]): boolean {
  return (
    list.length > 0 &&
    list.every((stage) => stage.label.trim() !== "" && stage.prompt.trim() !== "")
  );
}

function toStage(stage: ApiStage): Stage {
  return {
    id: String(stage.id),
    label: stage.label,
    prompt: stage.prompt,
    weight: stage.weight,
  };
}

function toInput(stage: Stage): StageInput {
  return { label: stage.label.trim(), prompt: stage.prompt.trim(), weight: stage.weight };
}

function renderFromJob(job: Job): RenderState {
  return {
    jobId: job.id,
    state: job.state,
    progress: job.progress,
    detail: job.detail ?? "",
    error: job.error,
  };
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function eventData<T extends { state?: string }>(event: Event): T | null {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") return null;
  try {
    return JSON.parse(event.data) as T;
  } catch {
    return null;
  }
}

function StageCard({
  stage,
  index,
  removable,
  onChange,
  onRemove,
}: {
  stage: Stage;
  index: number;
  removable: boolean;
  onChange: (s: Stage) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: stage.id });
  const style = { transform: CSS.Transform.toString(transform), transition };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={[
        "rounded-xl border border-white/10 bg-white/[0.03] p-4 transition",
        isDragging ? "opacity-70 ring-2 ring-amber-400/60" : "hover:border-white/20",
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <button
          {...attributes}
          {...listeners}
          aria-label="Drag to reorder"
          className="mt-1 cursor-grab rounded-md border border-white/10 px-2 py-1 text-xs text-white/50 active:cursor-grabbing"
        >
          ⠿
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-xs uppercase tracking-widest text-amber-300/80">Stage {index + 1}</span>
            <button
              onClick={onRemove}
              disabled={!removable}
              title={!removable ? `${MIN_STAGES}–${MAX_STAGES} stages` : undefined}
              className="text-xs text-white/35 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-30"
            >
              remove
            </button>
          </div>
          <input
            value={stage.label}
            onChange={(e) => onChange({ ...stage, label: e.target.value })}
            aria-label={`Stage ${index + 1} label`}
            className="mt-1 w-full bg-transparent text-lg font-semibold text-white outline-none"
          />
          <textarea
            value={stage.prompt}
            onChange={(e) => onChange({ ...stage, prompt: e.target.value })}
            aria-label={`Stage ${index + 1} prompt`}
            rows={2}
            className="mt-1 w-full resize-none bg-transparent text-sm text-white/65 outline-none"
          />
          <div className="mt-2 flex items-center gap-3 text-xs text-white/45">
            <label className="flex items-center gap-2">
              <span>weight</span>
              <input
                type="range"
                min={0.4}
                max={2}
                step={0.1}
                value={stage.weight}
                onChange={(e) => onChange({ ...stage, weight: Number(e.target.value) })}
                className="accent-amber-400"
              />
              <span className="tabular-nums text-white/70">{stage.weight.toFixed(2)}×</span>
            </label>
          </div>
        </div>
      </div>
    </li>
  );
}

export default function App() {
  const [initialProjectId] = useState(() => new URLSearchParams(window.location.search).get("project"));
  const [projectId, setProjectId] = useState<string | null>(initialProjectId);
  const [projectTitle, setProjectTitle] = useState<string | null>(null);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [description, setDescription] = useState("");
  const [takes, setTakes] = useState<Take[]>([]);
  const [pickedTake, setPickedTake] = useState<number | null>(null);
  const [render, setRender] = useState<RenderState | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamNote, setStreamNote] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(Boolean(initialProjectId));
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const stageListRef = useRef(stages);
  const saveTimerRef = useRef<number | null>(null);
  const saveSeqRef = useRef(0);
  const hydratingRef = useRef(false);
  const streamRef = useRef<EventSource | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  useEffect(() => {
    stageListRef.current = stages;
  }, [stages]);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(messageOf(e)));
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  useEffect(() => {
    return () => {
      streamRef.current?.close();
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, []);

  const openStream = useCallback((jobId: string, initial?: RenderState) => {
    streamRef.current?.close();
    setStreamNote(null);
    setRender(initial ?? { jobId, state: "queued", progress: 0, detail: "queued", error: null });

    const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);
    streamRef.current = source;

    source.onopen = () => setStreamNote(null);

    source.addEventListener("progress", (event) => {
      const data = eventData<{ state: string; progress: number; detail: string }>(event);
      if (!data) return;
      setStreamNote(null);
      setRender({
        jobId,
        state: data.state,
        progress: typeof data.progress === "number" ? data.progress : 0,
        detail: data.detail ?? "",
        error: null,
      });
    });

    source.addEventListener("done", (event) => {
      const data = eventData<{ state: string; takes: Take[] }>(event);
      if (data?.takes) {
        setTakes(data.takes);
        setPickedTake((current) => {
          const stillThere = data.takes.some((take) => take.id === current);
          return stillThere ? current : (data.takes[0]?.id ?? null);
        });
      }
      setRender({ jobId, state: "done", progress: 1, detail: "done", error: null });
      setStreamNote(null);
      source.close();
      if (streamRef.current === source) streamRef.current = null;
    });

    source.addEventListener("error", (event) => {
      const data = eventData<{ state: string; error?: string }>(event);
      if (data) {
        const message = data.error || "render failed";
        setRender({ jobId, state: "error", progress: 0, detail: "", error: message });
        setStreamNote(null);
        source.close();
        if (streamRef.current === source) streamRef.current = null;
      } else {
        setStreamNote("Connection lost — retrying…");
      }
    });
  }, []);

  useEffect(() => {
    if (!initialProjectId) {
      setReady(true);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    api
      .getProject(initialProjectId)
      .then((project) => {
        if (cancelled) return;
        hydratingRef.current = true;
        setProjectId(project.id);
        setProjectTitle(project.title);
        setStages(project.stages.map(toStage));
        setSourceUrl(project.source_url);
        setTakes(project.takes);
        setPickedTake(project.takes.find((take) => take.picked)?.id ?? project.takes[0]?.id ?? null);
        setSaveState("idle");
        setError(null);
        setReady(true);
        setLoading(false);

        if (project.job) {
          const restored = renderFromJob(project.job);
          setRender(restored);
          if (ACTIVE_RENDER_STATES.has(project.job.state)) openStream(project.job.id, restored);
        } else {
          setRender(null);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setError(`Could not load project ${initialProjectId}: ${messageOf(e)}`);
        setProjectId(null);
        setProjectTitle(null);
        setSourceUrl(null);
        setTakes([]);
        setRender(null);
        setSaveState("idle");
        setReady(true);
        setLoading(false);
        history.replaceState(null, "", window.location.pathname);
      });

    return () => {
      cancelled = true;
    };
  }, [initialProjectId, openStream]);

  const persistStages = useCallback(async (id: string, list: Stage[]): Promise<boolean> => {
    if (!isStagesValid(list)) return false;
    const seq = ++saveSeqRef.current;
    setSaveState("saving");
    try {
      await api.putStages(id, list.map(toInput));
      if (seq === saveSeqRef.current) setSaveState("saved");
      return true;
    } catch (e) {
      if (seq === saveSeqRef.current) {
        setSaveState("error");
        setError(messageOf(e));
      }
      return false;
    }
  }, []);

  useEffect(() => {
    if (!ready || !projectId) return;
    if (hydratingRef.current) {
      hydratingRef.current = false;
      return;
    }
    if (!isStagesValid(stages)) {
      setSaveState("idle");
      return;
    }

    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null;
      void persistStages(projectId, stages);
    }, 700);

    return () => {
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [stages, projectId, ready, persistStages]);

  const totalWeight = useMemo(() => stages.reduce((sum, stage) => sum + stage.weight, 0), [stages]);
  const invalidStages = !isStagesValid(stages);
  const renderActive = render !== null && ACTIVE_RENDER_STATES.has(render.state);
  const selectedTake = takes.find((take) => take.id === pickedTake) ?? takes[0] ?? null;
  const stageCountValid = stages.length >= MIN_STAGES && stages.length <= MAX_STAGES;

  const evolveBlocker = useMemo(() => {
    if (stages.length === 0) return "Describe the object to build a starter chain.";
    if (!sourceUrl) return "Upload a source photo first.";
    if (stages.length < MIN_STAGES) return `Add at least ${MIN_STAGES} stages to evolve.`;
    if (stages.length > MAX_STAGES) return `Keep the chain to ${MAX_STAGES} stages or fewer.`;
    if (invalidStages) return "Every stage needs a label and prompt.";
    return null;
  }, [stages.length, sourceUrl, invalidStages]);

  async function flushSave(): Promise<boolean> {
    if (!projectId) return true;
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    return persistStages(projectId, stageListRef.current);
  }

  function seedChain() {
    const value = description.trim();
    if (!value) return;
    setStages(buildStarterStages(value));
    setError(null);
  }

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setStages((items) => {
      const from = items.findIndex((i) => i.id === active.id);
      const to = items.findIndex((i) => i.id === over.id);
      return arrayMove(items, from, to);
    });
  }

  async function uploadFile(file: File) {
    if (!file.type.startsWith("image/")) {
      setError("That file is not an image. Choose a PNG, JPG or WebP.");
      return;
    }
    if (stages.length === 0) {
      setError("Describe the object first — that seeds your evolution chain.");
      return;
    }
    if (stages.length < MIN_STAGES || stages.length > MAX_STAGES) {
      setError(`A project needs between ${MIN_STAGES} and ${MAX_STAGES} stages.`);
      return;
    }
    if (!isStagesValid(stages)) {
      setError("Every stage needs a label and prompt before uploading.");
      return;
    }

    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    saveSeqRef.current += 1;
    streamRef.current?.close();
    streamRef.current = null;

    setUploading(true);
    setError(null);
    setStreamNote(null);

    try {
      const project = await api.createProject(file, stages.map(toInput));
      hydratingRef.current = true;
      setProjectId(project.id);
      setProjectTitle(project.title);
      setStages(project.stages.map(toStage));
      setSourceUrl(project.source_url);
      setTakes(project.takes);
      setPickedTake(project.takes[0]?.id ?? null);
      setRender(project.job ? renderFromJob(project.job) : null);
      setSaveState("saved");
      setReady(true);
      history.replaceState(null, "", `?project=${encodeURIComponent(project.id)}`);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setUploading(false);
    }
  }

  async function onEvolve() {
    if (!projectId) {
      setError("Upload a source photo first.");
      return;
    }
    if (stageListRef.current.length < MIN_STAGES || stageListRef.current.length > MAX_STAGES) {
      setError(`Render needs ${MIN_STAGES}-${MAX_STAGES} stages — this project has ${stageListRef.current.length}.`);
      return;
    }
    if (!isStagesValid(stageListRef.current)) {
      setError("Every stage needs a label and prompt before rendering.");
      return;
    }

    setError(null);
    setStreamNote(null);
    const saved = await flushSave();
    if (!saved) return;

    try {
      setRender({ jobId: "", state: "queued", progress: 0, detail: "queued", error: null });
      const { job_id } = await api.renderProject(projectId);
      openStream(job_id);
    } catch (e) {
      const message = messageOf(e);
      setError(message);
      setRender({ jobId: "", state: "error", progress: 0, detail: "", error: message });
    }
  }

  return (
    <div className="min-h-full bg-[#0d0f13] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-6">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-amber-300/80">Object Evolution</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">One object, one continuous take</h1>
            <p className="mt-2 max-w-xl text-sm text-white/55">
              Upload a photo, name its stages, and get a single unbroken metamorphosis — no cuts, no slideshow.
            </p>
          </div>
          <div className="text-right text-xs text-white/45">
            <div>
              cloud:{" "}
              <span className={health?.ok ? "text-emerald-400" : "text-red-400"}>
                {health ? (health.ok ? health.cloud?.status ?? "ok" : health.cloud?.error ?? "error") : "checking…"}
              </span>
            </div>
            <div className="mt-1">
              nodes: <span className="tabular-nums text-white/70">{meta?.nodes_total?.toLocaleString() ?? "—"}</span>
              {meta ? ` · LTX ${meta.ltx_nodes}` : ""}
            </div>
          </div>
        </header>

        {error && (
          <div className="mt-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            <div className="flex items-start justify-between gap-4">
              <span className="whitespace-pre-wrap break-words">{error}</span>
              <button onClick={() => setError(null)} className="shrink-0 text-xs text-red-200/60 hover:text-red-100">
                dismiss
              </button>
            </div>
          </div>
        )}

        {loading && (
          <div className="mt-6 rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-3 text-sm text-amber-100/80">
            Loading project {initialProjectId}…
          </div>
        )}

        <main className="mt-8 grid gap-8 lg:grid-cols-[1.15fr_1fr]">
          <section>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void uploadFile(file);
              }}
              className={[
                "flex items-center gap-4 rounded-xl border border-dashed px-4 py-3 transition",
                dragOver
                  ? "border-amber-300/70 bg-amber-400/10"
                  : "border-white/15 bg-white/[0.02] hover:border-white/25",
              ].join(" ")}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void uploadFile(file);
                }}
              />
              {sourceUrl ? (
                <img src={sourceUrl} alt="Source" className="h-16 w-16 rounded-lg border border-white/10 object-cover" />
              ) : (
                <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-white/10 text-2xl text-amber-300/70">
                  ↑
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-white/85">
                  {uploading ? "Uploading…" : sourceUrl ? "Source photo" : "Drop a photo to start"}
                </p>
                <p className="mt-0.5 truncate text-xs text-white/45">
                  {projectId ? (
                    <>
                      project {projectId.slice(0, 10)}…{projectTitle ? ` · ${projectTitle}` : ""}
                    </>
                  ) : (
                    "PNG, JPG or WebP · uploads start a new project"
                  )}
                </p>
              </div>
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:border-amber-300/60 hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {sourceUrl ? "Replace" : "Choose file"}
              </button>
            </div>

            <div className="mt-6 flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-widest text-white/50">Evolution chain</h2>
              {stages.length > 0 && (
                <div className="flex items-center gap-3">
                  <span className="text-xs text-white/35">
                    {MIN_STAGES}–{MAX_STAGES} stages
                  </span>
                  <button
                    onClick={() =>
                      setStages((s) => [
                        ...s,
                        {
                          id: `s${crypto.randomUUID()}`,
                          label: "New stage",
                          prompt: "describe the next form, keeping the same silhouette",
                          weight: 1.0,
                        },
                      ])
                    }
                    disabled={stages.length >= MAX_STAGES}
                    title={stages.length >= MAX_STAGES ? `${MIN_STAGES}–${MAX_STAGES} stages` : undefined}
                    className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:border-amber-300/60 hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-white/15 disabled:hover:text-white/70"
                  >
                    add stage
                  </button>
                </div>
              )}
            </div>

            {stages.length === 0 ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  seedChain();
                }}
                className="mt-4 rounded-xl border border-white/10 bg-white/[0.03] p-5"
              >
                <label htmlFor="object-description" className="text-sm font-medium text-white/85">
                  What is this object?
                </label>
                <p className="mt-1 text-xs text-white/45">
                  Describe it in a few words — we'll build a starter chain you can rewrite.
                </p>
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    id="object-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="a white anatomical skeleton on a black leather sofa"
                    autoFocus
                    className="min-w-0 flex-1 rounded-lg border border-white/15 bg-black/30 px-3 py-2 text-sm text-white outline-none placeholder:text-white/30 focus:border-amber-300/60"
                  />
                  <button
                    type="submit"
                    disabled={!description.trim()}
                    className="rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-300 disabled:cursor-not-allowed disabled:bg-amber-400/20 disabled:text-amber-200/60"
                  >
                    Start chain
                  </button>
                </div>
              </form>
            ) : (
              <>
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                  <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                    <ul className="mt-4 space-y-3">
                      {stages.map((stage, i) => (
                        <StageCard
                          key={stage.id}
                          stage={stage}
                          index={i}
                          removable={stages.length > MIN_STAGES}
                          onChange={(next) => setStages((all) => all.map((s) => (s.id === stage.id ? next : s)))}
                          onRemove={() => setStages((all) => all.filter((s) => s.id !== stage.id))}
                        />
                      ))}
                    </ul>
                  </SortableContext>
                </DndContext>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-white/45">
                  <span>
                    {stages.length} stages · <span className="tabular-nums">{totalWeight.toFixed(1)}</span> total weight
                    {saveState === "saving" && <span className="ml-2 text-amber-300/80">saving…</span>}
                    {saveState === "saved" && <span className="ml-2 text-emerald-400">saved</span>}
                    {saveState === "error" && <span className="ml-2 text-red-300">save failed</span>}
                  </span>
                  <span className={invalidStages || !stageCountValid ? "text-red-300" : undefined}>
                    {!stageCountValid
                      ? `${MIN_STAGES}–${MAX_STAGES} stages required to render`
                      : invalidStages
                        ? "every stage needs a label and prompt"
                        : `${MIN_STAGES}–${MAX_STAGES} stages · ready to evolve`}
                  </span>
                </div>
              </>
            )}
          </section>

          <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-sm uppercase tracking-widest text-white/50">Preview</h2>
              {projectId && <span className="text-xs text-white/30">{projectId.slice(0, 8)}…</span>}
            </div>

            {render && ACTIVE_RENDER_STATES.has(render.state) && (
              <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-400/5 p-3">
                <div className="flex items-center justify-between text-xs text-amber-100/80">
                  <span>{render.state === "queued" ? "queued" : "evolving"}</span>
                  <span className="tabular-nums">{Math.round(Math.max(0, Math.min(1, render.progress)) * 100)}%</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-amber-400 transition-all"
                    style={{ width: `${Math.max(0, Math.min(1, render.progress)) * 100}%` }}
                  />
                </div>
                <p className="mt-2 truncate text-xs text-white/55">{render.detail || "waiting for the worker…"}</p>
                {streamNote && <p className="mt-1 text-xs text-amber-300/80">{streamNote}</p>}
              </div>
            )}

            {render?.error && (
              <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                <p className="whitespace-pre-wrap break-words">{render.error}</p>
              </div>
            )}

            {takes.length > 0 ? (
              <div className="mt-4">
                <div className="grid grid-cols-2 gap-3">
                  {takes.map((take) => {
                    const selected = selectedTake?.id === take.id;
                    return (
                      <button
                        key={take.id}
                        type="button"
                        onClick={() => setPickedTake(take.id)}
                        aria-pressed={selected}
                        className={[
                          "overflow-hidden rounded-xl border text-left transition",
                          selected
                            ? "border-amber-400/80 ring-2 ring-amber-400/30"
                            : "border-white/10 hover:border-white/30",
                        ].join(" ")}
                      >
                        {take.url ? (
                          <video
                            src={take.url}
                            autoPlay
                            muted
                            loop
                            playsInline
                            className="aspect-[9/16] w-full bg-black object-cover"
                          />
                        ) : (
                          <div className="flex aspect-[9/16] w-full items-center justify-center bg-black/40 text-xs text-white/35">
                            no video
                          </div>
                        )}
                        <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs">
                          <span className="truncate text-white/60">
                            {take.label}
                            {take.duration_s ? ` · ${take.duration_s.toFixed(1)}s` : ""}
                          </span>
                          {selected && <span className="shrink-0 text-amber-300">selected</span>}
                        </div>
                      </button>
                    );
                  })}
                </div>
                {render?.state === "done" && (
                  <p className="mt-3 text-xs text-emerald-400/80">
                    render complete · {takes.length} {takes.length === 1 ? "take" : "takes"}
                  </p>
                )}
              </div>
            ) : (
              <div className="mt-4 flex aspect-[9/16] max-h-[420px] items-center justify-center overflow-hidden rounded-xl border border-dashed border-white/15 bg-black/40 text-sm text-white/35">
                {sourceUrl ? (
                  <img src={sourceUrl} alt="Source preview" className="h-full w-full object-contain" />
                ) : (
                  "your metamorphosis lands here"
                )}
              </div>
            )}

            <button
              onClick={() => void onEvolve()}
              disabled={Boolean(evolveBlocker) || uploading || renderActive}
              className={[
                "mt-5 w-full rounded-xl px-4 py-3 text-sm font-semibold transition",
                Boolean(evolveBlocker) || uploading || renderActive
                  ? "cursor-not-allowed bg-amber-400/20 text-amber-200/60"
                  : "bg-amber-400 text-black hover:bg-amber-300",
              ].join(" ")}
              title={evolveBlocker ?? (renderActive ? "Render in progress" : undefined)}
            >
              {renderActive
                ? `Evolving · ${Math.round(Math.max(0, Math.min(1, render?.progress ?? 0)) * 100)}%`
                : takes.length > 0
                  ? "Evolve again · 2 takes"
                  : "Evolve · 2 takes"}
            </button>
            {evolveBlocker && !renderActive && (
              <p className="mt-2 text-xs text-amber-200/70">{evolveBlocker}</p>
            )}
            <p className="mt-3 text-xs text-white/35">
              Stage images are guides inside one generation — the frames between them are generated, not stitched.
            </p>
          </section>
        </main>
      </div>
    </div>
  );
}
