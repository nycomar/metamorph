export type Health = {
  ok: boolean;
  key_loaded: boolean;
  cloud?: { status?: string; account?: string; error?: string };
};

export type Meta = { nodes_total: number; ltx_nodes: number; has_ltx_keyframer: boolean };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  health: () => get<Health>("/api/health"),
  meta: () => get<Meta>("/api/meta"),
};
