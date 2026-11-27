import type { TrainingCapability, TrainingDataType, TrainingFile } from '@/controllers/API/finetuneV2';

export function selectableTrainingModels(models: TrainingCapability[], dataType: TrainingDataType) {
    return models.filter(model => Boolean(model.capability_id && model.base_model_id && model.registered !== false)
        && model.input_types.includes(dataType) && ['lora', 'freeze', 'full'].some(method => model.training_methods.includes(method))
        && model.validation_status === 'gpu_smoke_passed' && model.model_ready !== false && model.ready !== false);
}
export function compatibleTrainingFiles(files: TrainingFile[], dataType: TrainingDataType) {
    return files.filter(file => file.dataset_report?.validated && file.dataset_report.data_type === dataType);
}
export function inferenceAnswer(result: Record<string, unknown>) {
    const answer = result.response ?? result.answer;
    return typeof answer === 'string' ? answer : JSON.stringify(result, null, 2);
}
export function downloadTrainingText(name: string, text: string) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function validTrainingParameters(parameters: Record<string, number>) {
    return Object.entries(parameters).every(([name, value]) => {
        if (!Number.isFinite(value)) return false;
        if (name === 'max_steps') return Number.isInteger(value) && (value === -1 || value > 0);
        return value > 0;
    });
}

const methodParameters: Record<string, string> = { lora_rank: 'lora', freeze_trainable_layers: 'freeze' };
// Only send the parameters of the chosen method; the others would be ignored or rejected by the training service.
export function methodTrainingParameters(parameters: Record<string, number>, method: string) {
    return Object.fromEntries(Object.entries(parameters).filter(([name]) => !methodParameters[name] || methodParameters[name] === method));
}
