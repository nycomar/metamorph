import { useEffect, useState } from "react";
import { api, type GalleryItem } from "./api";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function shortDate(value: string): string {
  return value.slice(0, 10);
}

export default function Gallery() {
  const [items, setItems] = useState<GalleryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .gallery()
      .then((result) => {
        if (!cancelled) setItems(result.projects);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(messageOf(e));
          setItems([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-full bg-[#0d0f13] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-6">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-amber-300/80">Object Evolution</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Gallery</h1>
            <p className="mt-2 max-w-xl text-sm text-white/55">
              Finished metamorphoses, newest first. Open one to keep evolving it.
            </p>
          </div>
          <a href="/" className="text-xs text-amber-300/70 hover:text-amber-200">
            ← studio
          </a>
        </header>

        {error && (
          <div className="mt-6 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {items === null && (
          <div className="mt-6 rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-3 text-sm text-amber-100/80">
            Loading gallery…
          </div>
        )}

        {items !== null && items.length === 0 && !error && (
          <div className="mt-10 rounded-xl border border-dashed border-white/15 bg-white/[0.02] px-6 py-16 text-center text-sm text-white/40">
            Nothing finished yet. Evolve an object in the studio and it will show up here.
          </div>
        )}

        {items !== null && items.length > 0 && (
          <main className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <a
                key={item.id}
                href={`/?project=${encodeURIComponent(item.id)}`}
                className="group overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] transition hover:border-amber-300/60"
              >
                <div className="relative aspect-[9/16] overflow-hidden bg-black">
                  {item.thumbnail_url ? (
                    <img
                      src={item.thumbnail_url}
                      alt={`Project ${item.id.slice(0, 8)}`}
                      loading="lazy"
                      className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.02]"
                    />
                  ) : item.take_url ? (
                    <video
                      src={item.take_url}
                      muted
                      loop
                      playsInline
                      autoPlay
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-xs text-white/30">
                      no preview
                    </div>
                  )}
                  {item.duration_s !== null && (
                    <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] tabular-nums text-white/80">
                      {item.duration_s.toFixed(1)}s
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between gap-2 px-3 py-2.5 text-xs">
                  <span className="truncate font-mono text-white/55">{item.id.slice(0, 10)}…</span>
                  <span className="shrink-0 text-white/30">{shortDate(item.created_at)}</span>
                </div>
              </a>
            ))}
          </main>
        )}
      </div>
    </div>
  );
}
