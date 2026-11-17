import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@bisheng/ui';
import { Select } from '@bisheng/ui';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { listTrainingDatasets } from '@/controllers/API/finetuneDatasets';
import { TrainingDataType, TrainingFile } from '@/controllers/API/finetuneV2';
import { DatasetImportDialog } from './DatasetImportDialog';
import { DatasetPreview } from './DatasetPreview';
import { SavedDatasetPreview } from './SavedDatasetPreview';

interface Props { dataType: TrainingDataType; files: TrainingFile[]; onChange: (files: TrainingFile[]) => void; onBusyChange?: (busy: boolean) => void }
export function CreateTaskList({ dataType, files, onChange, onBusyChange }: Props) {
    const { t } = useTranslation('model');
    const selectLabels = useSelectLabels();
    const [datasets, setDatasets] = useState<TrainingFile[]>([]);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [failed, setFailed] = useState(false);
    const [importOpen, setImportOpen] = useState(false);
    const [localFiles, setLocalFiles] = useState<Record<string, File>>({});
    const active = useRef(true);
    const requestId = useRef(0);
    const loadDatasets = useCallback(async (nextPage: number) => {
        const currentRequest = ++requestId.current;
        setLoading(true); setFailed(false);
        try {
            const result = await listTrainingDatasets(dataType, nextPage);
            if (!active.current || currentRequest !== requestId.current) return;
            setDatasets(old => nextPage === 1 ? result.data : [...old, ...result.data.filter(item => !old.some(existing => existing.id === item.id))]);
            setTotal(result.total); setPage(nextPage);
        } catch { if (active.current && currentRequest === requestId.current) setFailed(true); }
        finally { if (active.current && currentRequest === requestId.current) setLoading(false); }
    }, [dataType]);
    useEffect(() => {
        active.current = true; void loadDatasets(1);
        return () => { active.current = false; };
    }, [loadDatasets]);
    const handleImported = (file: TrainingFile, localFile?: File) => {
        if (localFile) setLocalFiles({ [file.dataset_report.sha256]: localFile });
        else setLocalFiles({});
        onChange([file]);
        setDatasets(old => [file, ...old.filter(item => item.id !== file.id)]);
        void loadDatasets(1);
    };
    const options = [...files, ...datasets.filter(item => !files.some(file => file.id === item.id))].filter(item => item.id);
    const sampleType = dataType === 'text' ? 'text' : dataType === 'image_text' ? 'image' : 'video';
    return <div className="space-y-3">
        <p className="text-sm text-muted-foreground">{t('finetune.datasetSelectHint')}</p>
        <div className="flex items-center gap-3 flex-wrap">
            <Select {...selectLabels} value={files[0]?.id || null} disabled={loading && !options.length} onChange={id => { const selected = options.find(file => file.id === String(id)); if (selected) onChange([selected]); }} className="max-w-[500px]" aria-label={t("finetune.datasetExistingVersion")} placeholder={t("finetune.datasetChooseVersion")} options={options.map(file => ({value: file.id, label: `${file.name} · ${(file.version_id || file.id).slice(0, 8)}`}))} />
            <Button type="button" variant="outlined" disabled={loading} onClick={() => void loadDatasets(1)}>{t('finetune.datasetRefresh')}</Button>
            <Button type="button" variant="outlined" onClick={() => setImportOpen(true)}>{t('finetune.datasetImport')}</Button>
            <a href={`${import.meta.env.BASE_URL}finetune-samples/bisheng-${sampleType}-smoke.zip`} download className="text-sm underline whitespace-nowrap">{t('finetune.downloadSampleFile')}</a>
        </div>
        {loading && <p role="status" className="text-sm">{t('finetune.datasetLoading')}</p>}
        {failed && <p role="alert" className="text-sm text-red-500">{t('finetune.datasetListFailed')}</p>}
        {!loading && !failed && !options.length && <p className="text-sm text-muted-foreground">{t('finetune.datasetEmpty')}</p>}
        {datasets.length < total && <Button type="button" variant="outlined" disabled={loading} onClick={() => void loadDatasets(page + 1)}>{t('finetune.datasetLoadMore')}</Button>}
        {files.map(file => <div key={file.id} className="border rounded-md p-3 space-y-1">
            <div className="flex justify-between items-center gap-3"><span>{file.name}</span><Button type="button" size="small" variant="outlined" onClick={() => onChange([])}>{t('finetune.datasetUnselect')}</Button></div>
            <p className="text-sm">{t('finetune.datasetChecked', { samples: file.dataset_report.samples, media: file.dataset_report.media })}</p>
            <p className="text-xs text-muted-foreground break-all">{t('finetune.datasetVersion')}: {file.version_id || file.id}</p>
            {file.create_time && <p className="text-xs text-muted-foreground">{t('finetune.datasetCreatedAt')}: {file.create_time}</p>}
            <p className="text-xs text-muted-foreground break-all">SHA-256: {file.dataset_report.sha256}</p>
            {dataType === 'video_text' && <p className="text-xs text-muted-foreground">{t('finetune.videoDecodeHint')}</p>}
            {localFiles[file.dataset_report.sha256] ? <DatasetPreview file={localFiles[file.dataset_report.sha256]} dataType={dataType} />
                : <SavedDatasetPreview versionId={file.version_id || file.id} />}
        </div>)}
        {importOpen && <DatasetImportDialog dataType={dataType} onClose={() => setImportOpen(false)} onImported={handleImported} onBusyChange={onBusyChange} />}
    </div>;
}
