/** Model metadata can change while the same conversation stays open. */
export const modelConfigRefresh = {
  staleTime: 30_000,
  refetchOnWindowFocus: 'always' as const,
  refetchOnReconnect: 'always' as const,
  refetchInterval: 30_000,
  refetchIntervalInBackground: false,
};

/** Resolve labels from the current response, including an explicitly cleared alias. */
export function normalizeModelNames<T extends { displayName?: string | null; name?: string | null }>(models: T[]) {
  return models.map(model => ({
    ...model,
    displayName: model.displayName?.trim() || model.name?.trim() || '',
  }));
}
