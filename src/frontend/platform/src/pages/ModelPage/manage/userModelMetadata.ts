export interface ConfiguredUserModel {
    id: string
    key?: string
    name?: string
    displayName?: string
    description?: string
    visual?: boolean
}

export interface ModelServer {
    id: number
    name: string
    models: Array<{ id: number; model_name: string; model_type: string; online: boolean }>
}

export function updateModelMetadata(
    models: ConfiguredUserModel[],
    model: { id: number; model_name: string },
    changes: Pick<ConfiguredUserModel, 'displayName' | 'visual'>,
): ConfiguredUserModel[] {
    const exists = models.some(row => String(row.id) === String(model.id))
    if (exists) return models.map(row => String(row.id) === String(model.id) ? { ...row, ...changes } : row)
    return [...models, { id: String(model.id), key: String(model.id), name: model.model_name, ...changes }]
}
