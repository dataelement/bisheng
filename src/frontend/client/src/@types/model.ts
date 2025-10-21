export interface ModelInfo {
    key: string | null;
    id: string;
    name: string | null;
    displayName: string | null;
}

export interface SelectModel {
    task_model: ModelInfo;
    embedding_model: ModelInfo;
    linsight_executor_mode: string;
    asr_model: ModelInfo;
    tts_model: ModelInfo;
}

export interface Response<T> {
    code: number;
    message: string;
    data: T;
}

export type SelectModelResponse = Response<SelectModel>;