interface PresetData {
    id: string;
    num: number;
    url: string;
    name: string;
}

interface ExtraParams {
    gpus: number;
    val_radio: number;
    learning_rate: number;
}

export interface TaskDB {
    server: number;
    base_model: number;
    model_name: string;
    base_model_name: string;
    extra_params: ExtraParams;
    preset_data: PresetData[];
    reason: string;
    report: any; // Replace 'any' with the actual type if 'report' has a specific structure
    user_name: string;
    update_time: string;
    model_id: number;
    id: string;
    method: string;
    train_data: any[]; // Replace 'any' with the actual type if 'train_data' has a specific structure
    status: number;
    log_path: string;
    user_id: number;
    create_time: string;
}

export interface FileDB {
    id: string;
    url: string;
    name: string;
    user_id: string;
    user_name: string;
    create_time: string | null;
    update_time: string | null;
}

export interface FileItem {
    id: string;
    checked: boolean;
    sampleSize: number;
    name: string;
    dataSource: string;
}