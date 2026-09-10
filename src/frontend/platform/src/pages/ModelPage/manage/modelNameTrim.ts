export function trimModelNames<T extends { model_name?: string | null }>(models: T[]): T[] {
    return models.map((model) => ({
        ...model,
        model_name: (model.model_name ?? "").trim(),
    }));
}

export function hasDuplicateModelName(models: { model_name?: string | null }[]): boolean {
    const seen = new Set<string>();
    for (const model of models) {
        const name = model.model_name ?? "";
        if (seen.has(name)) return true;
        seen.add(name);
    }
    return false;
}

export function hasInvalidModelName(models: { model_name?: string | null }[]): boolean {
    return models.some((model) => {
        const name = model.model_name ?? "";
        return !name || name.length > 100;
    });
}
