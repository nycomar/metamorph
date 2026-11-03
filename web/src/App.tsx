import { useEffect, useMemo, useState } from "react";
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
import { api, type Health, type Meta } from "./api";

type Stage = { id: string; label: string; prompt: string; seconds: number };

const DEFAULT_STAGES: Stage[] = [
  { id: "s1", label: "Metal ring", prompt: "a polished metal ring on dark stone, studio light", seconds: 1.4 },
  { id: "s2", label: "Living plant", prompt: "the same ring has become living plant matter, roots spreading", seconds: 1.6 },
  { id: "s3", label: "Organic flesh", prompt: "the same shape turns to organic flesh, wet and breathing", seconds: 1.6 },
  { id: "s4", label: "Mechanical organism", prompt: "the same form becomes a mechanical organism, brass and steel", seconds: 1.4 },
];

function StageCard({
  stage,
  index,
  onChange,
  onRemove,
}: {
  stage: Stage;
  index: number;
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
            <button onClick={onRemove} className="text-xs text-white/35 hover:text-red-300">
              remove
            </button>
          </div>
          <input
            value={stage.label}
            onChange={(e) => onChange({ ...stage, label: e.target.value })}
            className="mt-1 w-full bg-transparent text-lg font-semibold text-white outline-none"
          />
          <textarea
            value={stage.prompt}
            onChange={(e) => onChange({ ...stage, prompt: e.target.value })}
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
                value={stage.seconds}
                onChange={(e) => onChange({ ...stage, seconds: Number(e.target.value) })}
                className="accent-amber-400"
              />
              <span className="tabular-nums text-white/70">{stage.seconds.toFixed(1)}s</span>
            </label>
          </div>
        </div>
      </div>
    </li>
  );
}

export default function App() {
  const [stages, setStages] = useState<Stage[]>(DEFAULT_STAGES);
  const [health, setHealth] = useState<Health | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e)));
    api.meta().then(setMeta).catch(() => undefined);
  }, []);

  const total = useMemo(() => stages.reduce((a, s) => a + s.seconds, 0), [stages]);

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setStages((items) => {
      const from = items.findIndex((i) => i.id === active.id);
      const to = items.findIndex((i) => i.id === over.id);
      return arrayMove(items, from, to);
    });
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
            {error}
          </div>
        )}

        <main className="mt-8 grid gap-8 lg:grid-cols-[1.15fr_1fr]">
          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-widest text-white/50">Evolution chain</h2>
              <button
                onClick={() =>
                  setStages((s) => [
                    ...s,
                    { id: `s${crypto.randomUUID()}`, label: "New stage", prompt: "", seconds: 1.2 },
                  ])
                }
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:border-amber-300/60 hover:text-amber-200"
              >
                add stage
              </button>
            </div>

            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={stages.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                <ul className="mt-4 space-y-3">
                  {stages.map((stage, i) => (
                    <StageCard
                      key={stage.id}
                      stage={stage}
                      index={i}
                      onChange={(next) => setStages((all) => all.map((s) => (s.id === stage.id ? next : s)))}
                      onRemove={() => setStages((all) => all.filter((s) => s.id !== stage.id))}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>

            <div className="mt-4 flex items-center justify-between text-xs text-white/45">
              <span>
                {stages.length} stages · <span className="tabular-nums">{total.toFixed(1)}s</span> total
              </span>
              <span>3–5 stages is the sweet spot</span>
            </div>
          </section>

          <section className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <h2 className="text-sm uppercase tracking-widest text-white/50">Preview</h2>
            <div className="mt-4 flex aspect-[9/16] max-h-[420px] items-center justify-center rounded-xl border border-dashed border-white/15 bg-black/40 text-sm text-white/35">
              your metamorphosis lands here
            </div>
            <button
              disabled
              className="mt-5 w-full cursor-not-allowed rounded-xl bg-amber-400/20 px-4 py-3 text-sm font-semibold text-amber-200/60"
              title="The render pipeline lands next"
            >
              Evolve · 2 takes
            </button>
            <p className="mt-3 text-xs text-white/35">
              Stage images are guides inside one generation — the frames between them are generated, not stitched.
            </p>
          </section>
        </main>
      </div>
    </div>
  );
}
