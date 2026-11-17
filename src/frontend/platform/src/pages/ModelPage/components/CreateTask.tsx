import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@bisheng/ui';
import { Input } from '@bisheng/ui';
import { Label } from '@/components/bs-ui/label';
import { Select } from '@bisheng/ui';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { RadioGroup, Radio as RadioGroupItem } from '@bisheng/ui';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { discoverTrainingModels, listTrainingServices, preflightTraining, submitTraining,
    TrainingCapability, TrainingDataType, TrainingFile, TrainingRequest, TrainingService } from '@/controllers/API/finetuneV2';
import { CreateTaskList } from './CreateTaskList';
import { compatibleTrainingFiles, selectableTrainingModels, validTrainingParameters } from './finetuneHelpers';

interface Props { rtClick: () => void; gpuClick: () => void; onCancel: () => void; onCreate: (id: string) => void; servicesVersion?: number }
const initialParameters = { max_steps: 8, learning_rate: 0.0001, lora_rank: 8, cutoff_len: 1024,
    per_device_train_batch_size: 1, gradient_accumulation_steps: 1, num_train_epochs: 1 };
const dataTypes: TrainingDataType[] = ['text', 'image_text', 'video_text'];
export function CreateTask({ rtClick, gpuClick, onCancel, onCreate, servicesVersion }: Props) {
    const { t } = useTranslation('model');
    const selectLabels = useSelectLabels();
    const [services, setServices] = useState<TrainingService[]>([]);
    const [serviceId, setServiceId] = useState('');
    const [capabilities, setCapabilities] = useState<TrainingCapability[]>([]);
    const [capabilityId, setCapabilityId] = useState('');
    const [dataType, setDataType] = useState<TrainingDataType>('text');
    const [files, setFiles] = useState<TrainingFile[]>([]);
    const [modelName, setModelName] = useState('');
    const [maxStepsInput, setMaxStepsInput] = useState('8');
    const [parameters, setParameters] = useState<Record<string, number>>(initialParameters);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [datasetBusy, setDatasetBusy] = useState(false);
    const [discovering, setDiscovering] = useState(false);
    useEffect(() => {
        let active = true;
        void captureAndAlertRequestErrorHoc(listTrainingServices().then(rows => {
            if (active) setServices(rows.filter(row => row.id != null && String(row.id) !== '' && row.sft_endpoint));
        }));
        return () => { active = false; };
    }, [servicesVersion]);
    useEffect(() => {
        let active = true;
        setCapabilities([]); setCapabilityId('');
        if (!serviceId) { setDiscovering(false); return; }
        setDiscovering(true); setError('');
        void captureAndAlertRequestErrorHoc(discoverTrainingModels(Number(serviceId)).then(response => {
            if (active) setCapabilities(response.models);
        }).finally(() => { if (active) setDiscovering(false); }));
        return () => { active = false; };
    }, [serviceId, servicesVersion]);
    const models = selectableTrainingModels(capabilities, dataType);
    const selected = models.find(item => item.capability_id === capabilityId);
    const handleTypeChange = (value: TrainingDataType) => {
        setDataType(value); setCapabilityId(''); setFiles([]); setError('');
    };
    const handleCreate = async () => {
        setError('');
        if (!selected?.base_model_id || !serviceId) { setError(t('finetune.selectValidatedCapability')); return; }
        if (!/^[a-zA-Z][a-zA-Z\d_-]{0,49}$/.test(modelName)) { setError(t('finetune.modelNameHint')); return; }
        if (files.length !== 1 || compatibleTrainingFiles(files, dataType).length !== files.length) { setError(t('finetune.selectCheckedDataset')); return; }
        if (!validTrainingParameters(parameters)) { setError(t('finetune.invalidParameters')); return; }
        const request: TrainingRequest = { contract_version: 2, server: Number(serviceId), base_model: selected.base_model_id,
            capability_id: selected.capability_id, data_type: dataType, method: 'lora', model_name: modelName,
            extra_params: parameters, train_data: files, preset_data: [], dataset_report: { files: files.map(file => file.dataset_report) } };
        setBusy(true);
        try {
            const result = await preflightTraining(request);
            if (!result.passed) { setError(`${t('finetune.preflightFailed')}: ${result.checks.filter(check => !check.passed).map(check => `${check.name}: ${JSON.stringify(check.detail ?? '')}`).join('; ')}`); return; }
            const task = await submitTraining(request);
            onCreate(task.id);
        } catch (failure) {
            setError(t('finetune.submitFailed'));
            await captureAndAlertRequestErrorHoc(Promise.reject(failure));
        } finally { setBusy(false); }
    };
    return <div className="pt-2 px-2 pb-10 space-y-6 overflow-y-auto h-[calc(100vh-162px-var(--license-banner-h,0px))]">
        <div className="border-b pb-2 flex justify-between items-center"><h1>{t('finetune.createTrainingTask')}</h1><Button variant="outlined" onClick={rtClick}>{t('finetune.rtServiceManagement')}</Button></div>
        <fieldset disabled={busy} className="space-y-6">
            <div className="space-y-2"><Label>{t('finetune.dataType')}</Label><RadioGroup value={dataType} className="flex gap-6" onValueChange={handleTypeChange}>
                {dataTypes.map(type => <div key={type} className="flex items-center gap-2"><RadioGroupItem id={`training-${type}`} value={type} /><Label htmlFor={`training-${type}`}>{t(`finetune.type_${type}`)}</Label></div>)}
            </RadioGroup></div>
            <div className="space-y-2"><Label>{t('finetune.rtService')}</Label><div className="flex gap-3">
                <Select {...selectLabels} value={serviceId} onChange={value => setServiceId(value == null ? "" : String(value))} className="max-w-[400px]" aria-label={t("finetune.rtService")} placeholder={t("finetune.selectRTService")} options={services.filter(service => service.id != null).map(service => ({value: String(service.id), label: service.server}))} />
                <Button variant="outlined" onClick={gpuClick}>{t('finetune.gpuResourceUsage')}</Button>
            </div></div>
            <div className="space-y-2"><Label>{t('finetune.baseModel')}</Label>
                <Select {...selectLabels} value={capabilityId} onChange={value => setCapabilityId(value == null ? "" : String(value))} disabled={discovering || !models.length} className="max-w-[500px]" aria-label={t("finetune.baseModel")} placeholder={t("finetune.selectBaseModel")} options={models.map(model => ({value: model.capability_id, label: model.model_name}))} />
                <p className="text-sm text-muted-foreground">{t(discovering ? 'finetune.discoveringModels' : models.length ? 'finetune.modelSourceHint' : 'finetune.noCompatibleModels')}</p>
            </div>
            <div className="space-y-2"><Label htmlFor="training-name">{t('finetune.finetuneModelName')}</Label><Input id="training-name" value={modelName} onChange={event => setModelName(event.target.value)} placeholder="support-model-v1" className="max-w-[500px]" /><p className="text-sm text-muted-foreground">{t('finetune.modelNameHint')}</p></div>
            <div className="space-y-2 border-t pt-4"><Label>{t('finetune.dataset')}</Label><CreateTaskList key={dataType} dataType={dataType} files={files} onChange={setFiles} onBusyChange={setDatasetBusy} /></div>
            <div className="space-y-3 border-t pt-4"><Label>{t('finetune.trainingMethod')}: LoRA</Label><p className="text-sm text-muted-foreground">{t('finetune.smallRunHint')}</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">{Object.entries(parameters).map(([name, value]) => <div key={name} className="space-y-1"><Label htmlFor={`param-${name}`}>{t(`finetune.param_${name}`)}</Label><Input id={`param-${name}`} type={name === 'max_steps' ? 'text' : 'number'} inputMode={name === 'max_steps' ? 'numeric' : undefined} step={name === 'learning_rate' ? '0.00001' : name === 'num_train_epochs' ? '0.1' : '1'} min={name === 'max_steps' ? -1 : 0} value={name === 'max_steps' ? maxStepsInput : value} onChange={event => { if (name === 'max_steps') setMaxStepsInput(event.target.value); const parsed = event.target.value.trim() === '' ? NaN : Number(event.target.value); setParameters(old => ({ ...old, [name]: parsed })); }} /></div>)}</div>
            </div>
        </fieldset>
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        <div className="flex gap-3"><Button disabled={busy || datasetBusy || discovering} onClick={() => void handleCreate()}>{t(busy ? 'finetune.checkingAndSubmitting' : 'finetune.checkAndCreate')}</Button><Button disabled={busy || datasetBusy} variant="outlined" onClick={onCancel}>{t('bs:cancel')}</Button></div>
    </div>;
}
