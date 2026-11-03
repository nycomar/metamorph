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
  type ExportFormat,
  type Health,
  type Job,
  type Meta,
  type Project,
  type StageInput,
  type Take,
} from "./api";
import {
  MAX_STAGES,
  MIN_STAGES,
  emptyStage,
  evolveBlockerFor,
  isStagesValid,
  stagesFromProject,
  type Stage,
} from "./stageRules";

type RenderState = {
  jobId: string;
  state: string;
  progress: number;
  detail: string;
  error: string | null;
};

type SaveState = "idle" | "saving" | "saved" | "error";

const ACTIVE_RENDER_STATES = new Set(["queued", "running"]);

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
  rerollable,
  rerolling,
  onChange,
  onRemove,
  onReroll,
}: {
  stage: Stage;
  index: number;
  removable: boolean;
  rerollable: boolean;
  rerolling: boolean;
  onChange: (s: Stage) => void;
  onRemove: () => void;
  onReroll: () => void;
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
            <span className="text-xs uppercase tracking-widest text-amber-300/80">Transformation {index + 1}</span>
            <div className="flex items-center gap-3">
              <button
                onClick={onReroll}
                disabled={!rerollable || rerolling}
                title={!rerollable ? "Save the stage before re-rolling" : undefined}
                className="flex items-center gap-1 text-xs text-white/35 hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:text-white/35"
              >
                {rerolling && (
                  <span className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
                )}
                evolve this again
              </button>
              <button
                onClick={onRemove}
                disabled={!removable}
                title={!removable ? `${MIN_STAGES}–${MAX_STAGES} transformations` : undefined}
                className="text-xs text-white/35 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-30"
              >
                remove
              </button>
            </div>
          </div>
          <input
            value={stage.label}
            onChange={(e) => onChange({ ...stage, label: e.target.value })}
            aria-label={`Transformation ${index + 1} label`}
            placeholder="Fossil"
            className="mt-1 w-full bg-transparent text-lg font-semibold text-white outline-none placeholder:text-white/25"
          />
          <textarea
            value={stage.prompt}
            onChange={(e) => onChange({ ...stage, prompt: e.target.value })}
            aria-label={`Transformation ${index + 1} prompt`}
            placeholder="encrusted with pale fossil stone, cracks and sediment"
            rows={2}
            className="mt-1 w-full resize-none bg-transparent text-sm text-white/65 outline-none placeholder:text-white/25"
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
  const [pendingPhoto, setPendingPhoto] = useState<{ file: File; url: string } | null>(null);
  const [stages, setStages] = useState<Stage[]>(() => [emptyStage()]);
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
  const [pickingTake, setPickingTake] = useState<number | null>(null);
  const [exportingFormat, setExportingFormat] = useState<ExportFormat | null>(null);
  const [rerollStageId, setRerollStageId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const stageListRef = useRef(stages);
  const saveTimerRef = useRef<number | null>(null);
  const saveSeqRef = useRef(0);
  const hydratingRef = useRef(false);
  const streamRef = useRef<EventSource | null>(null);
  const pendingPhotoRef = useRef<{ file: File; url: string } | null>(null);
  const createTimerRef = useRef<number | null>(null);
  const createPromiseRef = useRef<Promise<Project | null> | null>(null);

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
      if (createTimerRef.current !== null) window.clearTimeout(createTimerRef.current);
      if (pendingPhotoRef.current) URL.revokeObjectURL(pendingPhotoRef.current.url);
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
        setStages(stagesFromProject(project.stages));
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
        setStages([emptyStage()]);
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
  const renderActive = render !== null && ACTIVE_RENDER_STATES.has(render.state);
  const selectedTake = takes.find((take) => take.id === pickedTake) ?? takes[0] ?? null;
  const displaySourceUrl = pendingPhoto?.url ?? sourceUrl;

  const evolveBlocker = evolveBlockerFor(displaySourceUrl, stages);

  const clearPendingPhoto = useCallback(() => {
    if (createTimerRef.current !== null) {
      window.clearTimeout(createTimerRef.current);
      createTimerRef.current = null;
    }
    if (pendingPhotoRef.current) URL.revokeObjectURL(pendingPhotoRef.current.url);
    pendingPhotoRef.current = null;
    setPendingPhoto(null);
  }, []);

  const createFromPhoto = useCallback(
    (file: File, list: Stage[]): Promise<Project | null> => {
      if (createPromiseRef.current) return createPromiseRef.current;
      if (!isStagesValid(list)) return Promise.resolve(null);

      if (createTimerRef.current !== null) {
        window.clearTimeout(createTimerRef.current);
        createTimerRef.current = null;
      }

      const promise = (async (): Promise<Project | null> => {
        saveSeqRef.current += 1;
        streamRef.current?.close();
        streamRef.current = null;
        setUploading(true);
        setError(null);
        setStreamNote(null);

        try {
          const project = await api.createProject(file, list.map(toInput));
          hydratingRef.current = true;
          setProjectId(project.id);
          setProjectTitle(project.title);
          setStages(stagesFromProject(project.stages));
          setSourceUrl(project.source_url);
          setTakes(project.takes);
          setPickedTake(project.takes[0]?.id ?? null);
          setRender(project.job ? renderFromJob(project.job) : null);
          setSaveState("saved");
          setReady(true);
          clearPendingPhoto();
          history.replaceState(null, "", `?project=${encodeURIComponent(project.id)}`);
          return project;
        } catch (e) {
          setError(messageOf(e));
          return null;
        } finally {
          setUploading(false);
        }
      })();

      createPromiseRef.current = promise;
      void promise.finally(() => {
        if (createPromiseRef.current === promise) createPromiseRef.current = null;
      });
      return promise;
    },
    [clearPendingPhoto],
  );

  useEffect(() => {
    if (!ready || !pendingPhoto || createPromiseRef.current) return;
    if (!isStagesValid(stages)) return;

    if (createTimerRef.current !== null) window.clearTimeout(createTimerRef.current);
    createTimerRef.current = window.setTimeout(() => {
      createTimerRef.current = null;
      const pending = pendingPhotoRef.current;
      if (pending) void createFromPhoto(pending.file, stageListRef.current);
    }, 500);

    return () => {
      if (createTimerRef.current !== null) {
        window.clearTimeout(createTimerRef.current);
        createTimerRef.current = null;
      }
    };
  }, [ready, pendingPhoto, stages, createFromPhoto]);

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setStages((items) => {
      const from = items.findIndex((i) => i.id === active.id);
      const to = items.findIndex((i) => i.id === over.id);
      return arrayMove(items, from, to);
    });
  }

  function uploadFile(file: File) {
    if (!file.type.startsWith("image/")) {
      setError("That file is not an image. Choose a PNG, JPG or WebP.");
      return;
    }

    if (pendingPhotoRef.current) URL.revokeObjectURL(pendingPhotoRef.current.url);
    const pending = { file, url: URL.createObjectURL(file) };
    pendingPhotoRef.current = pending;
    setPendingPhoto(pending);
    setError(null);
  }

  async function onPickTake(takeId: number) {
    if (pickingTake !== null) return;
    setPickingTake(takeId);
    setError(null);
    try {
      const picked = await api.pickTake(takeId);
      setTakes((items) => items.map((take) => ({ ...take, picked: take.id === picked.id })));
      setPickedTake(picked.id);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setPickingTake(null);
    }
  }

  async function onExport(format: ExportFormat) {
    if (!projectId || exportingFormat !== null) return;
    setExportingFormat(format);
    setError(null);
    try {
      const { blob, filename } = await api.exportProject(projectId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setExportingFormat(null);
    }
  }

  async function onReroll(stageIndex: number) {
    const list = stageListRef.current;
    const stage = list[stageIndex];
    if (!stage || renderActive) return;
    if (!displaySourceUrl) {
      setError("add your photo");
      return;
    }
    if (!isStagesValid(list)) {
      setError("write what it becomes for every transformation before rendering.");
      return;
    }

    setError(null);
    setStreamNote(null);

    let id = projectId;
    const pending = pendingPhotoRef.current;
    if (pending) {
      const project = await createFromPhoto(pending.file, list);
      if (!project) return;
      id = project.id;
    }
    if (!id) {
      setError("add your photo");
      return;
    }

    const saved = await persistStages(id, list);
    if (!saved) return;

    try {
      setRerollStageId(stage.id);
      setRender({
        jobId: "",
        state: "queued",
        progress: 0,
        detail: `re-rolling ${stage.label.trim() || `transformation ${stageIndex + 1}`}`,
        error: null,
      });
      const { job_id } = await api.rerollStage(id, stageIndex + 1);
      openStream(job_id);
    } catch (e) {
      const message = messageOf(e);
      setError(message);
      setRender({ jobId: "", state: "error", progress: 0, detail: "", error: message });
    } finally {
      setRerollStageId(null);
    }
  }

  async function onEvolve() {
    const list = stageListRef.current;
    if (!displaySourceUrl) {
      setError("add your photo");
      return;
    }
    if (list.length < MIN_STAGES || list.length > MAX_STAGES) {
      setError(`Evolve needs between ${MIN_STAGES} and ${MAX_STAGES} transformations — this project has ${list.length}.`);
      return;
    }
    if (!isStagesValid(list)) {
      setError("write what it becomes for every transformation before rendering.");
      return;
    }

    setError(null);
    setStreamNote(null);

    let id = projectId;
    const pending = pendingPhotoRef.current;
    if (pending) {
      const project = await createFromPhoto(pending.file, list);
      if (!project) return;
      id = project.id;
    }
    if (!id) {
      setError("add your photo");
      return;
    }

    const saved = await persistStages(id, list);
    if (!saved) return;

    try {
      setRender({ jobId: "", state: "queued", progress: 0, detail: "queued", error: null });
      const { job_id } = await api.renderProject(id);
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
              Drop a photo, describe what it becomes, and get a single unbroken metamorphosis — no cuts, no slideshow.
            </p>
          </div>
          <div className="text-right text-xs text-white/45">
            <a href="/gallery" className="mb-2 inline-block text-amber-300/70 hover:text-amber-200">
              gallery →
            </a>
            <div>
              cloud:{" "}
              <span className={health?.ok ? "text-emerald-400" : "text-red-400"}>
                {health ? (health.ok ? health.cloud?.status ?? "ok" : health.cloud?.error ?? "error") : "checking…"}
              </span>
            </div>
            <div className="mt-1">
              {meta ? `video: ${meta.video_model_label} · images: ${meta.image_model_label} · ` : ""}
              <span className="tabular-nums text-white/70">{meta?.nodes_total?.toLocaleString() ?? "—"}</span> nodes
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
              {displaySourceUrl ? (
                <img src={displaySourceUrl} alt="Source" className="h-16 w-16 rounded-lg border border-white/10 object-cover" />
              ) : (
                <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-white/10 text-2xl text-amber-300/70">
                  ↑
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-white/85">
                  {uploading
                    ? "Uploading…"
                    : displaySourceUrl
                      ? pendingPhoto
                        ? "Photo ready"
                        : "Source photo"
                      : "Drop a photo to start"}
                </p>
                <p className="mt-0.5 truncate text-xs text-white/45">
                  {displaySourceUrl ? "your photo is the first frame" : "PNG, JPG or WebP · your photo is the first frame"}
                </p>
                {projectId && (
                  <p className="mt-0.5 truncate text-xs text-white/30">
                    project {projectId.slice(0, 10)}…{projectTitle ? ` · ${projectTitle}` : ""}
                  </p>
                )}
              </div>
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:border-amber-300/60 hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {displaySourceUrl ? "Replace" : "Choose file"}
              </button>
            </div>

            <div className="mt-6 flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-widest text-white/50">What it becomes</h2>
              <div className="flex items-center gap-3">
                <span className="text-xs text-white/35">
                  {MIN_STAGES}–{MAX_STAGES} transformations
                </span>
                <button
                  onClick={() => setStages((s) => [...s, emptyStage()])}
                  disabled={stages.length >= MAX_STAGES}
                  title={stages.length >= MAX_STAGES ? `${MIN_STAGES}–${MAX_STAGES} transformations` : undefined}
                  className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:border-amber-300/60 hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-white/15 disabled:hover:text-white/70"
                >
                  add transformation
                </button>
              </div>
            </div>

            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                <ul className="mt-4 space-y-3">
                  {stages.map((stage, i) => (
                    <StageCard
                      key={stage.id}
                      stage={stage}
                      index={i}
                      removable={stages.length > MIN_STAGES}
                      rerollable={Boolean(displaySourceUrl) && isStagesValid(stages) && !renderActive && !uploading}
                      rerolling={rerollStageId === stage.id}
                      onChange={(next) => setStages((all) => all.map((s) => (s.id === stage.id ? next : s)))}
                      onRemove={() => setStages((all) => all.filter((s) => s.id !== stage.id))}
                      onReroll={() => void onReroll(i)}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-white/45">
              <span>
                {stages.length} {stages.length === 1 ? "transformation" : "transformations"} ·{" "}
                <span className="tabular-nums">{totalWeight.toFixed(1)}</span> total weight
                {saveState === "saving" && <span className="ml-2 text-amber-300/80">saving…</span>}
                {saveState === "saved" && <span className="ml-2 text-emerald-400">saved</span>}
                {saveState === "error" && <span className="ml-2 text-red-300">save failed</span>}
              </span>
              <span className={evolveBlocker ? "text-red-300" : undefined}>
                {evolveBlocker ?? `${stages.length} of ${MAX_STAGES} transformations · ready to evolve`}
              </span>
            </div>
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
                        onClick={() => void onPickTake(take.id)}
                        disabled={pickingTake !== null}
                        aria-pressed={selected}
                        className={[
                          "overflow-hidden rounded-xl border text-left transition disabled:cursor-wait",
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
                          {pickingTake === take.id ? (
                            <span className="shrink-0 text-amber-300/80">saving…</span>
                          ) : (
                            selected && <span className="shrink-0 text-amber-300">selected</span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
                {selectedTake && (
                  <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-xs uppercase tracking-widest text-white/45">Export selected take</span>
                      {exportingFormat && (
                        <span className="flex items-center gap-1.5 text-xs text-amber-300/80">
                          <span className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
                          encoding…
                        </span>
                      )}
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2">
                      {([
                        ["916", "9:16"],
                        ["169", "16:9"],
                        ["webp", "WebP loop"],
                      ] as const).map(([format, label]) => (
                        <button
                          key={format}
                          type="button"
                          onClick={() => void onExport(format)}
                          disabled={exportingFormat !== null || pickingTake !== null}
                          className="flex items-center justify-center gap-1.5 rounded-lg border border-white/15 px-2 py-2 text-xs text-white/70 transition hover:border-amber-300/60 hover:text-amber-200 disabled:cursor-wait disabled:opacity-40"
                        >
                          {exportingFormat === format && (
                            <span className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
                          )}
                          {label}
                        </button>
                      ))}
                    </div>
                    <p className="mt-2 text-[11px] text-white/30">
                      One encode at a time — the first export of a take can take a minute.
                    </p>
                  </div>
                )}
                {render?.state === "done" && (
                  <p className="mt-3 text-xs text-emerald-400/80">
                    render complete · {takes.length} {takes.length === 1 ? "take" : "takes"}
                  </p>
                )}
              </div>
            ) : (
              <div className="mt-4 flex aspect-[9/16] max-h-[420px] items-center justify-center overflow-hidden rounded-xl border border-dashed border-white/15 bg-black/40 text-sm text-white/35">
                {displaySourceUrl ? (
                  <img src={displaySourceUrl} alt="Source preview" className="h-full w-full object-contain" />
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
                  ? "Evolve again"
                  : "Evolve"}
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
