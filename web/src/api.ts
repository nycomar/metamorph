export type Health = {
  ok: boolean;
  key_loaded: boolean;
  cloud?: { status?: string; account?: string; error?: string };
};

export type Meta = { nodes_total: number; ltx_nodes: number; has_ltx_keyframer: boolean };

export type StageInput = { label: string; prompt: string; weight: number };

export type ApiStage = {
  id: number;
  position: number;
  label: string;
  prompt: string;
  weight: number;
  image_url: string | null;
};

export type Take = {
  id: number;
  label: string;
  url: string | null;
  duration_s: number | null;
  picked: boolean;
  created_at: string;
};

export type Job = {
  id: string;
  kind: string;
  state: string;
  progress: number;
  detail: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ExportFormat = "916" | "169" | "webp";

export type GalleryItem = {
  id: string;
  created_at: string;
  thumbnail_url: string | null;
  take_url: string | null;
  duration_s: number | null;
};

export type Project = {
  id: string;
  title: string | null;
  created_at: string;
  status: string;
  stage_count: number;
  source_url: string | null;
  stages: ApiStage[];
  takes: Take[];
  job?: Job;
};

async function errorMessage(path: string, init: RequestInit | undefined, res: Response): Promise<string> {
  let message = `${init?.method ?? "GET"} ${path}: HTTP ${res.status}`;
  const text = await res.text();
  if (text) {
    try {
      const body = JSON.parse(text) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail) message = JSON.stringify(body.detail);
      else message = text.slice(0, 400);
    } catch {
      message = text.slice(0, 400);
    }
  }
  return message;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(await errorMessage(path, init, res));
  return (await res.json()) as T;
}

async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await errorMessage(path, undefined, res));

  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
  const filename = match ? decodeURIComponent(match[1].replace(/"$/, "")) : path.split("/").pop() || "export";
  return { blob: await res.blob(), filename };
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export const api = {
  health: () => get<Health>("/api/health"),
  meta: () => get<Meta>("/api/meta"),
  getProject: (id: string) => get<Project>(`/api/projects/${encodeURIComponent(id)}`),
  createProject: (source: File, stages: StageInput[], title?: string) => {
    const body = new FormData();
    body.append("source", source);
    body.append("stages", JSON.stringify(stages));
    if (title) body.append("title", title);
    return request<Project>("/api/projects", { method: "POST", body });
  },
  putStages: (id: string, stages: StageInput[]) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}/stages`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stages),
    }),
  renderProject: (id: string) =>
    request<{ job_id: string }>(`/api/projects/${encodeURIComponent(id)}/render`, {
      method: "POST",
    }),
  pickTake: (takeId: number) =>
    request<Take>(`/api/takes/${encodeURIComponent(takeId)}/pick`, { method: "POST" }),
  rerollStage: (id: string, position: number) =>
    request<{ job_id: string }>(
      `/api/projects/${encodeURIComponent(id)}/stages/${encodeURIComponent(position)}/reroll`,
      { method: "POST" },
    ),
  exportProject: (id: string, format: ExportFormat) =>
    download(`/api/projects/${encodeURIComponent(id)}/export?format=${format}`),
  gallery: () => get<{ projects: GalleryItem[] }>("/api/gallery"),
};
