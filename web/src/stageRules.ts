import type { ApiStage } from "./api";

export type Stage = { id: string; label: string; prompt: string; weight: number };

export const MIN_STAGES = 1;
export const MAX_STAGES = 5;

export function emptyStage(): Stage {
  return { id: `s${crypto.randomUUID()}`, label: "", prompt: "", weight: 1.0 };
}

export function isStagesValid(list: Stage[]): boolean {
  return (
    list.length >= MIN_STAGES &&
    list.length <= MAX_STAGES &&
    list.every((stage) => stage.label.trim() !== "" && stage.prompt.trim() !== "")
  );
}

export function isLegacyOriginal(stage: ApiStage): boolean {
  return (
    stage.label.trim().toLowerCase() === "original" ||
    stage.prompt.trim().toLowerCase().includes(", unchanged")
  );
}

export function stagesFromProject(apiStages: ApiStage[]): Stage[] {
  const stages = apiStages.filter((stage) => !isLegacyOriginal(stage)).map((stage) => ({
    id: String(stage.id),
    label: stage.label,
    prompt: stage.prompt,
    weight: stage.weight,
  }));
  return stages.length > 0 ? stages : [emptyStage()];
}

export function evolveBlockerFor(sourceUrl: string | null, list: Stage[]): string | null {
  if (!sourceUrl) return "add your photo";
  if (list.length < MIN_STAGES) return "add a transformation";
  if (list.length > MAX_STAGES) return `max ${MAX_STAGES} transformations`;
  if (!isStagesValid(list)) return "write what it becomes";
  return null;
}
