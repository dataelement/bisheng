export function hasValidWorkbenchEmbeddingModelId(value: unknown): boolean {
  if (typeof value === "number") {
    return Number.isInteger(value) && value > 0;
  }

  if (typeof value !== "string") return false;

  return /^[1-9]\d*$/.test(value.trim());
}
