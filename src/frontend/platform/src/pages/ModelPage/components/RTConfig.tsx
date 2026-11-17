import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Button } from '@bisheng/ui';
import { Input } from '@bisheng/ui';
import { Label } from '@/components/bs-ui/label';
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { addTrainingService, deleteTrainingService, discoverTrainingModels, listTrainingServices,
    TrainingCapability, TrainingService } from '@/controllers/API/finetuneV2';

interface Props { open: boolean; onChange: () => void }
export function RTConfig({ open, onChange }: Props) {
    const { t } = useTranslation('model');
    const [services, setServices] = useState<TrainingService[]>([]);
    const [name, setName] = useState('');
    const [address, setAddress] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [models, setModels] = useState<Record<number, TrainingCapability[]>>({});
    useEffect(() => {
        if (!open) return;
        void captureAndAlertRequestErrorHoc(listTrainingServices().then(setServices));
    }, [open]);
    const handleAdd = async () => {
        setError('');
        try {
            const url = new URL(address);
            if (!name.trim() || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || (url.pathname !== '/' && url.pathname !== '')) {
                setError(t('finetune.serviceAddressHint')); return;
            }
        } catch { setError(t('finetune.serviceAddressHint')); return; }
        setBusy(true);
        try {
            await addTrainingService(name.trim(), address.replace(/\/$/, ''));
            setServices(await listTrainingServices()); setName(''); setAddress('');
        } catch (failure) { await captureAndAlertRequestErrorHoc(Promise.reject(failure)); }
        finally { setBusy(false); }
    };
    const handleTest = async (service: TrainingService) => {
        setBusy(true); setError('');
        setModels(previous => { const next = { ...previous }; delete next[service.id]; return next; });
        try { const result = await discoverTrainingModels(service.id); setModels(previous => ({ ...previous, [service.id]: result.models })); }
        catch (failure) { setError(t('finetune.serviceTestFailed')); await captureAndAlertRequestErrorHoc(Promise.reject(failure)); }
        finally { setBusy(false); }
    };
    const handleDelete = (service: TrainingService) => bsConfirm({ desc: t('finetune.confirmDeleteService', { name: service.server }), onOk: async next => {
        next(); await captureAndAlertRequestErrorHoc(deleteTrainingService(service.id).then(() => setServices(previous => previous.filter(item => item.id !== service.id))));
    } });
    return <Dialog open={open} onOpenChange={onChange}><DialogContent className="max-w-[820px]"><DialogHeader><DialogTitle>{t('finetune.rtServiceManagement')}</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">{t('finetune.serviceNetworkHint')}</p>
        <div className="space-y-3 max-h-[45vh] overflow-y-auto">{services.filter(service => service.sft_endpoint).map(service => <div className="border rounded-md p-3 space-y-2" key={service.id}>
            <div className="flex items-center justify-between gap-2"><div><p>{service.server}</p><p className="text-sm text-muted-foreground break-all">{service.sft_endpoint}</p></div><div className="flex gap-2"><Button size="small" disabled={busy} onClick={() => void handleTest(service)}>{t('finetune.testAndDiscover')}</Button><Button size="small" disabled={busy} variant="outlined" onClick={() => handleDelete(service)}>{t('bs:delete')}</Button></div></div>
            {models[service.id] && <div className="text-sm"><p>{t('finetune.serviceModelsFound', { count: models[service.id].length })}</p>{models[service.id].map(model => <p key={model.capability_id}>{model.model_name} · {model.input_types.map(type => t(`finetune.type_${type}`)).join(' / ')} · {t(model.ready === false || model.model_ready === false ? 'finetune.modelFilesNotReady' : model.validation_status === 'gpu_smoke_passed' ? 'finetune.validated' : 'finetune.notValidated')}</p>)}</div>}
        </div>)}</div>
        <div className="border-t pt-4 space-y-3"><Label htmlFor="ft-name">{t('finetune.machineName')}</Label><Input id="ft-name" value={name} onChange={event => setName(event.target.value)} placeholder={t('finetune.serviceNameExample')} /><Label htmlFor="ft-address">{t('finetune.serviceAddress')}</Label><Input id="ft-address" value={address} onChange={event => setAddress(event.target.value)} placeholder="http://training.example.com:8000" /><p className="text-xs text-muted-foreground">{t('finetune.serviceAddressHint')}</p><Button disabled={busy} onClick={() => void handleAdd()}>{t('finetune.saveService')}</Button></div>
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
    </DialogContent></Dialog>;
}
