import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Input } from '@bisheng/ui';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Label } from '@/components/bs-ui/label';
import { TrainingDataType, TrainingFile, uploadTrainingFile } from '@/controllers/API/finetuneV2';
import { safeDatasetImportError } from './DatasetImportDialog';

interface Props {
    dataType: TrainingDataType;
    onClose: () => void;
    onImported: (file: TrainingFile) => void;
    onBusyChange?: (busy: boolean) => void;
}
export function TemporaryDatasetUpload({ dataType, onClose, onImported, onBusyChange }: Props) {
    const { t } = useTranslation('model');
    const [file, setFile] = useState<File>();
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState<number>();
    const [error, setError] = useState('');
    const active = useRef(true);
    useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
    const handleUpload = async () => {
        setError('');
        if (!file) { setError(t('finetune.datasetChooseFile')); return; }
        const limit = /\.jsonl?$/i.test(file.name) ? 200 * 1024 ** 2 : 2 * 1024 ** 3;
        if (file.size > limit) { setError(t('finetune.datasetUploadSizeLimit')); return; }
        setBusy(true); onBusyChange?.(true);
        try {
            const result = await uploadTrainingFile(file, value => { if (active.current) setProgress(value); });
            if (!active.current) return;
            if (result.dataset_report.data_type !== dataType) { setError(t('finetune.datasetTypeMismatch')); return; }
            onImported(result); onClose();
        } catch (failure) {
            if (active.current) setError(safeDatasetImportError(failure, { endpoint: '' }, t('finetune.datasetImportFailed'), t('finetune.datasetErrorDetail')));
        } finally {
            if (active.current) { setBusy(false); setProgress(undefined); }
            onBusyChange?.(false);
        }
    };
    return <Dialog open onOpenChange={value => { if (!value && !busy) onClose(); }}>
        <DialogContent className="max-w-[600px]" onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onInteractOutside={event => event.preventDefault()}>
            <DialogHeader><DialogTitle>{t('finetune.temporaryUpload')}</DialogTitle><DialogDescription>{t('finetune.temporaryUploadHint')}</DialogDescription></DialogHeader>
            <div className="space-y-3"><Label htmlFor="temporary-dataset">{t('finetune.uploadDataset')}</Label>
                <Input id="temporary-dataset" type="file" disabled={busy} accept={dataType === 'text' ? '.json,.jsonl,.zip' : '.zip'} onChange={event => setFile(event.target.files?.[0])} />
                {progress !== undefined && <p role="status">{progress}%</p>}
                {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
                <div className="flex gap-3"><Button disabled={busy} onClick={() => void handleUpload()}>{t('finetune.datasetImportAndCheck')}</Button><Button variant="outlined" disabled={busy} onClick={onClose}>{t('bs:cancel')}</Button></div>
            </div>
        </DialogContent>
    </Dialog>;
}
